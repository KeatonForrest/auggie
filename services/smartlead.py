"""smartlead.py - Smartlead.ai integration: API key validation, campaign management, lead pushing."""

import logging
from datetime import datetime, timezone

import httpx

from database import (
    get_integration, update_list_account_pushed,
)

logger = logging.getLogger(__name__)

SMARTLEAD_API_BASE = "https://server.smartlead.ai/api/v1"


async def validate_api_key(api_key: str) -> bool:
    """Validate a Smartlead API key by listing campaigns."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{SMARTLEAD_API_BASE}/campaigns",
            params={"api_key": api_key},
        )
        return resp.status_code == 200


async def _get_api_key(user_id: int) -> str:
    """Get a user's Smartlead API key from integrations table."""
    integration = await get_integration(user_id, "smartlead")
    if not integration:
        raise RuntimeError("Smartlead not connected")
    return integration["access_token"]


async def list_campaigns(user_id: int) -> list[dict]:
    """List all campaigns for the user's Smartlead account."""
    api_key = await _get_api_key(user_id)
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{SMARTLEAD_API_BASE}/campaigns",
            params={"api_key": api_key},
        )
        resp.raise_for_status()
        data = resp.json()
    return [
        {"id": c.get("id"), "name": c.get("name", "")}
        for c in data if isinstance(c, dict)
    ]


async def add_leads_to_campaign(
    user_id: int,
    campaign_id: str,
    leads: list[dict],
) -> dict:
    """Add leads to a Smartlead campaign.

    Each lead should have: email, first_name, last_name, company_name,
    and optionally custom_fields dict.
    """
    api_key = await _get_api_key(user_id)
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{SMARTLEAD_API_BASE}/campaigns/{campaign_id}/leads",
            params={"api_key": api_key},
            json={"lead_list": leads},
        )
        resp.raise_for_status()
        return resp.json()


def _emails_to_smartlead_sequences(emails: list[dict]) -> list[dict]:
    """Convert Auggie email format to Smartlead sequences format.

    Auggie format: [{"email_number": 1, "subject": "...", "body": "..."}, ...]
    Smartlead format: [{"seq_number": 1, "seq_delay_details": {...}, "seq_variants": [...]}]
    """
    sequences = []
    for i, email in enumerate(emails):
        delay_days = 0 if i == 0 else 3  # First email immediate, then 3-day gaps
        sequences.append({
            "seq_number": i + 1,
            "seq_delay_details": {"delay_in_days": delay_days},
            "variant_distribution_type": "MANUAL_EQUAL",
            "seq_variants": [{
                "subject": email.get("subject", ""),
                "email_body": f"<p>{_plain_to_html(email.get('body', ''))}</p>",
                "variant_label": "A",
                "variant_distribution_percentage": 100,
            }],
        })
    return sequences


def _plain_to_html(text: str) -> str:
    """Convert plain text to simple HTML paragraphs."""
    import html
    escaped = html.escape(text)
    return escaped.replace("\n\n", "</p><p>").replace("\n", "<br>")


async def create_campaign_with_sequences(
    user_id: int,
    campaign_name: str,
    emails: list[dict],
    leads: list[dict] | None = None,
    timezone_str: str = "America/New_York",
) -> dict:
    """Create a Smartlead campaign with Auggie-generated email sequences.

    Requires 3 API calls: create campaign, add sequences, set schedule.

    Args:
        user_id: The user creating the campaign.
        campaign_name: Name for the campaign (e.g., "Auggie – Acme Corp").
        emails: List of email dicts from outreach_drafts (email_number, subject, body).
        leads: Optional list of leads to add to the campaign.
        timezone_str: Timezone for campaign schedule (default: America/New_York).

    Returns:
        {"campaign_id": str, "name": str} on success, or {"error": str} on failure.
    """
    api_key = await _get_api_key(user_id)

    async with httpx.AsyncClient(timeout=30.0) as client:
        # 1. Create the campaign
        create_resp = await client.post(
            f"{SMARTLEAD_API_BASE}/campaigns/create",
            params={"api_key": api_key},
            json={"name": campaign_name},
        )
        if create_resp.status_code >= 400:
            logger.error("Smartlead create campaign failed: %s %s", create_resp.status_code, create_resp.text[:500])
            return {"error": f"Failed to create campaign: {create_resp.text[:200]}"}

        campaign_data = create_resp.json()
        campaign_id = campaign_data.get("id")
        if not campaign_id:
            return {"error": "No campaign ID returned from Smartlead"}

        # 2. Add sequences
        sequences_payload = {"sequences": _emails_to_smartlead_sequences(emails)}
        seq_resp = await client.post(
            f"{SMARTLEAD_API_BASE}/campaigns/{campaign_id}/sequences",
            params={"api_key": api_key},
            json=sequences_payload,
        )
        if seq_resp.status_code >= 400:
            logger.warning("Smartlead add sequences failed for campaign %s: %s", campaign_id, seq_resp.text[:500])
            # Campaign exists but sequences failed - still return campaign ID

        # 3. Set schedule (9am-5pm weekdays)
        schedule_payload = {
            "timezone": timezone_str,
            "days_of_the_week": [1, 2, 3, 4, 5],  # Mon-Fri (0=Sun, 6=Sat)
            "start_hour": "09:00",
            "end_hour": "17:00",
            "min_time_btw_emails": 10,
            "max_new_leads_per_day": 50,
        }
        sched_resp = await client.post(
            f"{SMARTLEAD_API_BASE}/campaigns/{campaign_id}/schedule",
            params={"api_key": api_key},
            json=schedule_payload,
        )
        if sched_resp.status_code >= 400:
            logger.warning("Smartlead set schedule failed for campaign %s: %s", campaign_id, sched_resp.text[:500])

        # 4. Optionally add leads
        if leads:
            try:
                await add_leads_to_campaign(user_id, str(campaign_id), leads)
            except Exception as e:
                logger.warning("Failed to add leads to new Smartlead campaign %s: %s", campaign_id, e)

        return {"campaign_id": str(campaign_id), "name": campaign_name}


async def push_campaigns_to_smartlead(
    user_id: int,
    accounts: list[dict],
    drafts_by_account: dict[int, list[dict]],
    contacts_by_account: dict[int, list[dict]] | None = None,
) -> dict:
    """Bulk create Smartlead campaigns with Auggie-generated sequences.

    Creates one campaign per account with personalized email sequences.
    Optionally includes contacts as leads in each campaign.

    Args:
        user_id: The user performing the push.
        accounts: List of list_account dicts.
        drafts_by_account: Map of account_id -> list of email dicts from outreach_drafts.
        contacts_by_account: Optional map of account_id -> list of contact dicts.

    Returns:
        {"campaigns_created": int, "skipped": int, "errors": int, "campaign_ids": list}
    """
    campaigns_created = 0
    skipped = 0
    errors = 0
    campaign_ids = []

    for account in accounts:
        account_id = account["id"]
        emails = drafts_by_account.get(account_id)
        if not emails:
            skipped += 1
            continue

        # Build leads list if contacts provided
        leads = None
        if contacts_by_account:
            contacts = contacts_by_account.get(account_id, [])
            if contacts:
                leads = []
                for contact in contacts:
                    email = contact.get("email")
                    if not email:
                        continue
                    leads.append({
                        "email": email,
                        "first_name": contact.get("first_name", ""),
                        "last_name": contact.get("last_name", ""),
                        "company_name": account.get("company_name", ""),
                        "custom_fields": {
                            "company_url": account.get("company_url", ""),
                            "pain_score": str(account.get("pain_score", "")),
                            "fit_score": str(account.get("fit_score", "")),
                            "composite_score": str(account.get("composite_score", "")),
                            "title": contact.get("title", ""),
                        },
                    })

        company_name = account.get("company_name", "Unknown")
        result = await create_campaign_with_sequences(
            user_id,
            f"Auggie – {company_name}",
            emails,
            leads=leads,
        )

        if "error" in result:
            errors += 1
            logger.warning("Failed to create Smartlead campaign for %s: %s", company_name, result["error"])
        else:
            campaigns_created += 1
            campaign_ids.append(result["campaign_id"])
            await update_list_account_pushed(account_id, "smartlead_campaign", {
                "campaign_id": result["campaign_id"],
                "pushed_at": datetime.now(timezone.utc).isoformat(),
            })

    return {
        "campaigns_created": campaigns_created,
        "skipped": skipped,
        "errors": errors,
        "campaign_ids": campaign_ids,
    }


async def push_accounts_to_smartlead(
    user_id: int,
    campaign_id: str,
    accounts: list[dict],
    contacts_by_account: dict[int, list[dict]],
) -> dict:
    """Push selected accounts with contacts to a Smartlead campaign.

    Returns {"pushed": int, "skipped": int, "errors": int}.
    """
    leads = []
    account_ids = []

    for account in accounts:
        account_id = account["id"]
        contacts = contacts_by_account.get(account_id, [])
        if not contacts:
            continue

        for contact in contacts:
            email = contact.get("email")
            if not email:
                continue
            lead = {
                "email": email,
                "first_name": contact.get("first_name", ""),
                "last_name": contact.get("last_name", ""),
                "company_name": account.get("company_name", ""),
                "custom_fields": {
                    "company_url": account.get("company_url", ""),
                    "pain_score": str(account.get("pain_score", "")),
                    "fit_score": str(account.get("fit_score", "")),
                    "composite_score": str(account.get("composite_score", "")),
                    "title": contact.get("title", ""),
                },
            }
            leads.append(lead)
            account_ids.append(account_id)

    if not leads:
        return {"pushed": 0, "skipped": len(accounts), "errors": 0}

    try:
        await add_leads_to_campaign(user_id, campaign_id, leads)
        pushed_account_ids = set(account_ids)
        for aid in pushed_account_ids:
            await update_list_account_pushed(aid, "smartlead", {
                "campaign_id": campaign_id,
                "pushed_at": datetime.now(timezone.utc).isoformat(),
            })
        return {
            "pushed": len(leads),
            "skipped": len(accounts) - len(pushed_account_ids),
            "errors": 0,
        }
    except Exception as e:
        logger.exception("Failed to push leads to Smartlead")
        return {"pushed": 0, "skipped": 0, "errors": len(leads), "error": str(e)[:500]}
