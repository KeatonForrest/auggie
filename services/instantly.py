"""instantly.py - Instantly.ai integration: API key validation, campaign management, lead pushing."""

import logging
from datetime import datetime, timezone

import httpx

from database import (
    get_integration, update_list_account_pushed,
)

logger = logging.getLogger(__name__)

INSTANTLY_API_BASE = "https://api.instantly.ai/api/v1"


async def validate_api_key(api_key: str) -> bool:
    """Validate an Instantly API key by listing campaigns."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{INSTANTLY_API_BASE}/campaign/list",
            params={"api_key": api_key},
        )
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
            f"{INSTANTLY_API_BASE}/campaign/list",
            params={"api_key": api_key},
        )
        resp.raise_for_status()
        return resp.json()


async def create_campaign(user_id: int, name: str) -> dict:
    """Create a new Instantly campaign."""
    api_key = await _get_api_key(user_id)
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{INSTANTLY_API_BASE}/campaign/create",
            json={"api_key": api_key, "name": name},
        )
        resp.raise_for_status()
        return resp.json()


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
            f"{INSTANTLY_API_BASE}/lead/add",
            json={
                "api_key": api_key,
                "campaign_id": campaign_id,
                "skip_if_in_workspace": True,
                "leads": leads,
            },
        )
        resp.raise_for_status()
        return resp.json()


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
