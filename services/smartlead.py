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
