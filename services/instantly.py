"""instantly.py - Instantly.ai integration: API key validation, campaign management, lead pushing."""

import logging
from datetime import datetime, timezone

import httpx

from database import (
    get_integration, update_list_account_pushed,
)

logger = logging.getLogger(__name__)

INSTANTLY_API_BASE = "https://api.instantly.ai/api/v2"


def _auth_headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}"}


async def validate_api_key(api_key: str) -> bool:
    """Validate an Instantly API key by listing campaigns."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{INSTANTLY_API_BASE}/campaigns",
            headers=_auth_headers(api_key),
            params={"limit": 1},
        )
        if resp.status_code != 200:
            logger.warning("Instantly v2 validation failed: %s %s", resp.status_code, resp.text[:500])
        return resp.status_code == 200


async def _get_api_key(user_id: int) -> str:
    """Get a user's Instantly API key from integrations table."""
    integration = await get_integration(user_id, "instantly")
    if not integration:
        raise RuntimeError("Instantly not connected")
    return integration["access_token"]


async def list_campaigns(user_id: int) -> list[dict]:
    """List all campaigns for the user's Instantly account."""
    api_key = await _get_api_key(user_id)
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{INSTANTLY_API_BASE}/campaigns",
            headers=_auth_headers(api_key),
        )
        if resp.status_code != 200:
            logger.error("Instantly list_campaigns failed: %s %s", resp.status_code, resp.text[:500])
        resp.raise_for_status()
        data = resp.json()
    logger.info("Instantly list_campaigns response type=%s keys=%s", type(data).__name__, list(data.keys()) if isinstance(data, dict) else "n/a")
    # v2 may return { items: [...] }, { data: [...] }, or a plain list
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = data.get("items", data.get("data", []))
    else:
        items = []
    return [
        {"id": c.get("id"), "name": c.get("name", "")}
        for c in items if isinstance(c, dict)
    ]


async def add_leads_to_campaign(
    user_id: int,
    campaign_id: str,
    leads: list[dict],
) -> dict:
    """Add leads to an Instantly campaign.

    Each lead should have: email, first_name, last_name, company_name,
    and optionally custom_variables dict.
    """
    api_key = await _get_api_key(user_id)
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{INSTANTLY_API_BASE}/leads",
            headers=_auth_headers(api_key),
            json={
                "campaign_id": campaign_id,
                "skip_if_in_workspace": True,
                "leads": leads,
            },
        )
        resp.raise_for_status()
        return resp.json()


def _emails_to_instantly_sequences(emails: list[dict]) -> list[dict]:
    """Convert Auggie email format to Instantly sequences format.

    Auggie format: [{"email_number": 1, "subject": "...", "body": "..."}, ...]
    Instantly format: [{"steps": [{"type": "email", "delay": 0, "variants": [{"subject": "...", "body": "..."}]}]}]
    """
    steps = []
    for i, email in enumerate(emails):
        delay = 0 if i == 0 else 3  # First email immediate, then 3-day gaps
        steps.append({
            "type": "email",
            "delay": delay,
            "variants": [{
                "subject": email.get("subject", ""),
                "body": email.get("body", ""),
            }],
        })
    return [{"steps": steps}]


def _default_campaign_schedule(tz: str = "America/New_York") -> dict:
    """Build default campaign schedule: 9am-5pm weekdays."""
    return {
        "schedules": [{
            "name": "Default",
            "timing": {"from": "09:00", "to": "17:00"},
            "days": {"sun": False, "mon": True, "tue": True, "wed": True, "thu": True, "fri": True, "sat": False},
            "timezone": tz,
        }]
    }


async def create_campaign_with_sequences(
    user_id: int,
    campaign_name: str,
    emails: list[dict],
    leads: list[dict] | None = None,
    timezone_str: str = "America/New_York",
) -> dict:
    """Create an Instantly campaign with Auggie-generated email sequences.

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

    payload = {
        "name": campaign_name,
        "campaign_schedule": _default_campaign_schedule(timezone_str),
        "sequences": _emails_to_instantly_sequences(emails),
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{INSTANTLY_API_BASE}/campaigns",
            headers=_auth_headers(api_key),
            json=payload,
        )
        if resp.status_code >= 400:
            logger.error("Instantly create campaign failed: %s %s", resp.status_code, resp.text[:500])
            return {"error": f"Failed to create campaign: {resp.text[:200]}"}

        data = resp.json()
        campaign_id = data.get("id")

        # Optionally add leads
        if leads and campaign_id:
            try:
                await add_leads_to_campaign(user_id, campaign_id, leads)
            except Exception as e:
                logger.warning("Failed to add leads to new campaign %s: %s", campaign_id, e)

        return {"campaign_id": campaign_id, "name": campaign_name}


async def push_campaigns_to_instantly(
    user_id: int,
    accounts: list[dict],
    drafts_by_account: dict[int, list[dict]],
    contacts_by_account: dict[int, list[dict]] | None = None,
) -> dict:
    """Bulk create Instantly campaigns with Auggie-generated sequences.

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
                        "custom_variables": {
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
            logger.warning("Failed to create campaign for %s: %s", company_name, result["error"])
        else:
            campaigns_created += 1
            campaign_ids.append(result["campaign_id"])
            await update_list_account_pushed(account_id, "instantly_campaign", {
                "campaign_id": result["campaign_id"],
                "pushed_at": datetime.now(timezone.utc).isoformat(),
            })

    return {
        "campaigns_created": campaigns_created,
        "skipped": skipped,
        "errors": errors,
        "campaign_ids": campaign_ids,
    }


async def push_accounts_to_instantly(
    user_id: int,
    campaign_id: str,
    accounts: list[dict],
    contacts_by_account: dict[int, list[dict]],
) -> dict:
    """Push selected accounts with contacts to an Instantly campaign.

    Args:
        user_id: The user performing the push.
        campaign_id: Instantly campaign ID to push to.
        accounts: List of list_account dicts (with id, company_name, company_url, etc.).
        contacts_by_account: Map of account_id -> list of contact dicts (from enriched_contacts).

    Returns:
        {"pushed": int, "skipped": int, "errors": int}
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
                "custom_variables": {
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
        result = await add_leads_to_campaign(user_id, campaign_id, leads)
        # Mark accounts as pushed
        pushed_account_ids = set(account_ids)
        for aid in pushed_account_ids:
            await update_list_account_pushed(aid, "instantly", {
                "campaign_id": campaign_id,
                "pushed_at": datetime.now(timezone.utc).isoformat(),
            })
        return {
            "pushed": len(leads),
            "skipped": len(accounts) - len(pushed_account_ids),
            "errors": 0,
        }
    except Exception as e:
        logger.exception("Failed to push leads to Instantly")
        return {"pushed": 0, "skipped": 0, "errors": len(leads), "error": str(e)[:500]}
