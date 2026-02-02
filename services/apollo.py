"""apollo.py - Apollo.io: contact enrichment + integration (API key, saved list import)."""

import logging

import httpx
from typing import Optional
from database import get_integration

logger = logging.getLogger(__name__)



# =============================================================================
# Integration functions (API key connect, saved list import)
# =============================================================================

async def get_firmographics_for_user(user_id: int, domain: str) -> Optional[str]:
    """Fetch firmographic data using a user's connected Apollo API key.

    Returns formatted string for Claude prompt, or None if not connected/no data.
    """
    try:
        integration = await get_integration(user_id, "apollo")
        if not integration:
            return None

        api_key = integration["access_token"]
        domain = domain.replace("https://", "").replace("http://", "").split("/")[0].replace("www.", "")

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.apollo.io/v1/mixed_companies/search",
                headers={"Content-Type": "application/json", "X-Api-Key": api_key},
                json={
                    "q_organization_domains": domain,
                    "page": 1,
                    "per_page": 1,
                },
            )
            if response.status_code != 200:
                return None

            data = response.json()
            orgs = data.get("organizations", []) or data.get("accounts", [])
            if not orgs:
                return None

            org = orgs[0]

        lines = []
        lines.append(f"**Company:** {org.get('name', domain)}")
        if org.get("industry"):
            lines.append(f"**Industry:** {org['industry']}")
        if org.get("estimated_num_employees"):
            lines.append(f"**Employees:** {org['estimated_num_employees']}")
        if org.get("annual_revenue_printed"):
            lines.append(f"**Revenue:** {org['annual_revenue_printed']}")
        if org.get("annual_revenue"):
            lines.append(f"**Revenue (raw):** ${org['annual_revenue']:,.0f}")
        if org.get("founded_year"):
            lines.append(f"**Founded:** {org['founded_year']}")
        if org.get("total_funding"):
            lines.append(f"**Total Funding:** ${org['total_funding']:,.0f}")
        if org.get("total_funding_printed"):
            lines.append(f"**Total Funding:** {org['total_funding_printed']}")
        if org.get("latest_funding_round_date"):
            lines.append(f"**Latest Funding Round:** {org['latest_funding_round_date']}")
        if org.get("latest_funding_stage"):
            lines.append(f"**Latest Funding Stage:** {org['latest_funding_stage']}")
        if org.get("latest_funding_round_amount"):
            lines.append(f"**Latest Round Amount:** ${org['latest_funding_round_amount']:,.0f}")
        if org.get("publicly_traded_symbol"):
            lines.append(f"**Ticker:** {org['publicly_traded_symbol']}")
            lines.append(f"**Publicly Traded:** Yes")

        if len(lines) <= 1:
            return None

        lines.append("")
        lines.append("(This is CONFIRMED firmographic data from Apollo.io — use it to validate or override inferred company size/industry for Fit scoring.)")
        return "\n".join(lines)

    except Exception as e:
        logger.warning("Apollo firmographics fetch failed (non-fatal): %s", e)
        return None


APOLLO_API_BASE = "https://api.apollo.io/v1"


def _plain_to_html(text: str) -> str:
    """Convert plain text to simple HTML paragraphs."""
    import html as html_mod
    escaped = html_mod.escape(text)
    return escaped.replace("\n\n", "</p><p>").replace("\n", "<br>")


async def _create_apollo_sequence_with_emails(
    api_key: str,
    company_name: str,
    emails: list[dict],
) -> str | None:
    """Create an Apollo sequence (emailer_campaign) with email steps.

    Returns the campaign ID, or None on failure.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        # 1. Create the sequence / emailer campaign
        seq_resp = await client.post(
            f"{APOLLO_API_BASE}/emailer_campaigns",
            headers={"Content-Type": "application/json", "X-Api-Key": api_key},
            json={
                "name": f"Auggie – {company_name}",
            },
        )
        if seq_resp.status_code >= 400:
            logger.warning("Apollo sequence create failed: %s", seq_resp.text[:200])
            return None
        campaign_id = seq_resp.json().get("emailer_campaign", {}).get("id")
        if not campaign_id:
            logger.warning("Apollo sequence create returned no ID: %s", seq_resp.text[:200])
            return None

        # 2. Add email steps
        for i, email in enumerate(emails):
            step_resp = await client.post(
                f"{APOLLO_API_BASE}/emailer_steps",
                headers={"Content-Type": "application/json", "X-Api-Key": api_key},
                json={
                    "emailer_campaign_id": campaign_id,
                    "priority": "A",
                    "type": "auto_email",
                    "wait_days": 3 if i > 0 else 0,
                    "subject": email.get("subject", ""),
                    "body": f"<p>{_plain_to_html(email.get('body', ''))}</p>",
                },
            )
            if step_resp.status_code >= 400:
                logger.warning("Apollo step create failed: %s", step_resp.text[:200])

    return campaign_id


async def _get_contacts_for_org(api_key: str, org_id: str) -> list[str]:
    """Fetch contact IDs for an Apollo organization."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{APOLLO_API_BASE}/mixed_people/search",
            headers={"Content-Type": "application/json", "X-Api-Key": api_key},
            json={
                "organization_ids": [org_id],
                "page": 1,
                "per_page": 25,
            },
        )
        if resp.status_code >= 400:
            logger.warning("Apollo contact search failed for org %s: %s", org_id, resp.text[:200])
            return []
        data = resp.json()
        return [p["id"] for p in data.get("people", []) if p.get("id")]


async def _add_contacts_to_sequence(api_key: str, campaign_id: str, contact_ids: list[str]) -> int:
    """Add contacts to an Apollo emailer campaign. Returns number added."""
    if not contact_ids:
        return 0
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{APOLLO_API_BASE}/emailer_campaigns/{campaign_id}/add_contact_ids",
            headers={"Content-Type": "application/json", "X-Api-Key": api_key},
            json={
                "contact_ids": contact_ids,
            },
        )
        if resp.status_code >= 400:
            logger.warning("Apollo add contacts failed for campaign %s: %s", campaign_id, resp.text[:200])
            return 0
        return len(contact_ids)


async def push_sequences_to_apollo(
    user_id: int,
    accounts: list[dict],
    drafts_by_account: dict[int, list[dict]],
) -> dict:
    """Create Apollo sequences with Auggie-generated email content.

    Creates one emailer_campaign per account, then adds contacts from the
    Apollo org (if source_id is available).

    Returns {"sequences_created": int, "skipped": int, "errors": int, "created_ids": [...], "contacts_added": int}.
    """
    api_key = await _get_integration_api_key(user_id)
    sequences_created = 0
    skipped = 0
    errors = 0
    created_ids = []
    contacts_added = 0

    for account in accounts:
        emails = drafts_by_account.get(account["id"])
        if not emails:
            skipped += 1
            continue

        created_id = await _create_apollo_sequence_with_emails(
            api_key, account.get("company_name", "Unknown"), emails,
        )
        if created_id:
            sequences_created += 1
            created_ids.append(created_id)

            # Auto-add contacts if we have the Apollo org ID
            org_id = account.get("source_id")
            if org_id:
                contact_ids = await _get_contacts_for_org(api_key, org_id)
                added = await _add_contacts_to_sequence(api_key, created_id, contact_ids)
                contacts_added += added
        else:
            errors += 1

    return {
        "sequences_created": sequences_created,
        "skipped": skipped,
        "errors": errors,
        "created_ids": created_ids,
        "contacts_added": contacts_added,
    }


async def validate_integration_api_key(api_key: str) -> bool:
    """Validate an Apollo API key by making a test call."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{APOLLO_API_BASE}/auth/health",
            headers={"Content-Type": "application/json", "X-Api-Key": api_key},
        )
        return resp.status_code == 200


async def _get_integration_api_key(user_id: int) -> str:
    """Get a user's Apollo integration API key from integrations table."""
    integration = await get_integration(user_id, "apollo")
    if not integration:
        raise RuntimeError("Apollo not connected")
    return integration["access_token"]


async def list_saved_lists(user_id: int) -> list[dict]:
    """List saved organization lists from Apollo."""
    api_key = await _get_integration_api_key(user_id)
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{APOLLO_API_BASE}/labels",
            headers={"Content-Type": "application/json", "X-Api-Key": api_key},
        )
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else data.get("labels", [])


async def fetch_list_companies(user_id: int, list_id: str, page: int = 1) -> dict:
    """Fetch companies from a saved Apollo list.

    Returns {"organizations": [...], "pagination": {...}}.
    """
    api_key = await _get_integration_api_key(user_id)
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{APOLLO_API_BASE}/mixed_companies/search",
            headers={"Content-Type": "application/json", "X-Api-Key": api_key},
            json={
                "label_ids": [list_id],
                "page": page,
                "per_page": 100,
            },
        )
        resp.raise_for_status()
        return resp.json()
