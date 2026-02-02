"""hubspot.py - HubSpot CRM integration: OAuth, company import, score writeback."""

import logging
from datetime import datetime, timezone, timedelta

import httpx

from config import get_settings
from database import (
    get_integration, update_integration_tokens,
)

logger = logging.getLogger(__name__)

HUBSPOT_AUTH_URL = "https://app.hubspot.com/oauth/authorize"
HUBSPOT_TOKEN_URL = "https://api.hubapi.com/oauth/v1/token"
HUBSPOT_API_BASE = "https://api.hubapi.com"

SCOPES = "oauth crm.objects.companies.read crm.objects.companies.write crm.schemas.companies.write"


def get_authorize_url(state: str) -> str:
    """Build the HubSpot OAuth authorization URL."""
    settings = get_settings()
    redirect_uri = f"{settings.app_url}/integrations/hubspot/callback"
    return (
        f"{HUBSPOT_AUTH_URL}"
        f"?client_id={settings.hubspot_client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&scope={SCOPES}"
        f"&state={state}"
    )


async def exchange_code(code: str) -> dict:
    """Exchange authorization code for tokens."""
    settings = get_settings()
    redirect_uri = f"{settings.app_url}/integrations/hubspot/callback"
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            HUBSPOT_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "client_id": settings.hubspot_client_id,
                "client_secret": settings.hubspot_client_secret,
                "redirect_uri": redirect_uri,
                "code": code,
            },
        )
        resp.raise_for_status()
        return resp.json()


async def refresh_access_token(user_id: int) -> str:
    """Refresh HubSpot access token if expired. Returns valid access token."""
    integration = await get_integration(user_id, "hubspot")
    if not integration:
        raise RuntimeError("HubSpot not connected")

    # Check if token is still valid (with 5-minute buffer)
    expires_at = integration.get("token_expires_at")
    if expires_at and expires_at > datetime.now(timezone.utc) + timedelta(minutes=5):
        return integration["access_token"]

    # Refresh
    settings = get_settings()
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            HUBSPOT_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": settings.hubspot_client_id,
                "client_secret": settings.hubspot_client_secret,
                "refresh_token": integration["refresh_token"],
            },
        )
        resp.raise_for_status()
        data = resp.json()

    new_expires = datetime.now(timezone.utc) + timedelta(seconds=data.get("expires_in", 21600))
    await update_integration_tokens(
        user_id, "hubspot",
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token"),
        token_expires_at=new_expires,
    )
    return data["access_token"]


async def get_valid_token(user_id: int) -> str:
    """Get a valid HubSpot access token, refreshing if needed."""
    return await refresh_access_token(user_id)


async def fetch_companies(user_id: int, limit: int = 100, after: str | None = None) -> dict:
    """Fetch companies from HubSpot CRM.

    Returns {"results": [...], "paging": {"next": {"after": "..."}}} or similar.
    """
    token = await get_valid_token(user_id)
    params = {
        "limit": min(limit, 100),
        "properties": "name,domain,industry,numberofemployees,city,state,country",
    }
    if after:
        params["after"] = after

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{HUBSPOT_API_BASE}/crm/v3/objects/companies",
            headers={"Authorization": f"Bearer {token}"},
            params=params,
        )
        resp.raise_for_status()
        return resp.json()


async def _ensure_custom_properties(token: str) -> None:
    """Create Auggie score properties on HubSpot if they don't exist."""
    properties = [
        {"name": "auggie_pain_score", "label": "Auggie Pain Score", "type": "number", "fieldType": "number",
         "groupName": "companyinformation", "description": "Pain score from Auggie research (0-100)"},
        {"name": "auggie_fit_score", "label": "Auggie Fit Score", "type": "number", "fieldType": "number",
         "groupName": "companyinformation", "description": "Fit score from Auggie research (0-100)"},
        {"name": "auggie_timing_score", "label": "Auggie Timing Score", "type": "number", "fieldType": "number",
         "groupName": "companyinformation", "description": "Timing score from Auggie research (0-100)"},
        {"name": "auggie_composite_score", "label": "Auggie Composite Score", "type": "number", "fieldType": "number",
         "groupName": "companyinformation", "description": "Composite score from Auggie research (0-100)"},
    ]

    async with httpx.AsyncClient(timeout=15.0) as client:
        for prop in properties:
            resp = await client.post(
                f"{HUBSPOT_API_BASE}/crm/v3/properties/companies",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=prop,
            )
            if resp.status_code == 409:
                continue  # Property already exists
            if resp.status_code >= 400:
                logger.warning("Failed to create HubSpot property %s: %s", prop["name"], resp.text)


async def write_scores_to_hubspot(
    user_id: int,
    hubspot_company_id: str,
    pain_score: int | None,
    fit_score: int | None,
    timing_score: int | None,
    composite_score: int | None,
) -> bool:
    """Write Auggie scores back to a HubSpot company record."""
    token = await get_valid_token(user_id)

    # Ensure properties exist (idempotent)
    await _ensure_custom_properties(token)

    properties = {}
    if pain_score is not None:
        properties["auggie_pain_score"] = str(pain_score)
    if fit_score is not None:
        properties["auggie_fit_score"] = str(fit_score)
    if timing_score is not None:
        properties["auggie_timing_score"] = str(timing_score)
    if composite_score is not None:
        properties["auggie_composite_score"] = str(composite_score)

    if not properties:
        return True

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.patch(
            f"{HUBSPOT_API_BASE}/crm/v3/objects/companies/{hubspot_company_id}",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"properties": properties},
        )
        if resp.status_code >= 400:
            logger.error("HubSpot writeback failed for company %s: %s", hubspot_company_id, resp.text)
            return False
        return True


async def write_list_scores_to_hubspot(user_id: int, list_source: dict, accounts: list[dict]) -> int:
    """Write scores for all completed accounts in a HubSpot-sourced list.

    Returns the number of successfully updated companies.
    """
    hubspot_map = list_source.get("hubspot_company_map", {})
    if not hubspot_map:
        return 0

    updated = 0
    for account in accounts:
        if account.get("status") != "completed":
            continue
        company_url = account.get("company_url", "")
        hubspot_id = hubspot_map.get(company_url)
        if not hubspot_id:
            continue

        success = await write_scores_to_hubspot(
            user_id,
            hubspot_id,
            pain_score=account.get("pain_score"),
            fit_score=account.get("fit_score"),
            timing_score=account.get("timing_score"),
            composite_score=account.get("composite_score"),
        )
        if success:
            updated += 1

    return updated
