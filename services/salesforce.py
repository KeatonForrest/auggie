"""salesforce.py - Salesforce CRM integration: OAuth, account import, score writeback."""

import logging
from datetime import datetime, timezone, timedelta

import httpx

from config import get_settings
from database import (
    get_integration, update_integration_tokens,
)

logger = logging.getLogger(__name__)

SALESFORCE_AUTH_URL = "https://login.salesforce.com/services/oauth2/authorize"
SALESFORCE_TOKEN_URL = "https://login.salesforce.com/services/oauth2/token"
SCOPES = "api refresh_token"


def get_authorize_url(state: str) -> str:
    """Build the Salesforce OAuth authorization URL."""
    settings = get_settings()
    redirect_uri = f"{settings.app_url}/integrations/salesforce/callback"
    return (
        f"{SALESFORCE_AUTH_URL}"
        f"?response_type=code"
        f"&client_id={settings.salesforce_client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&scope={SCOPES}"
        f"&state={state}"
    )


async def exchange_code(code: str) -> dict:
    """Exchange authorization code for tokens."""
    settings = get_settings()
    redirect_uri = f"{settings.app_url}/integrations/salesforce/callback"
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            SALESFORCE_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "client_id": settings.salesforce_client_id,
                "client_secret": settings.salesforce_client_secret,
                "redirect_uri": redirect_uri,
                "code": code,
            },
        )
        resp.raise_for_status()
        return resp.json()


async def refresh_access_token(user_id: int) -> tuple[str, str]:
    """Refresh Salesforce access token if expired. Returns (access_token, instance_url)."""
    integration = await get_integration(user_id, "salesforce")
    if not integration:
        raise RuntimeError("Salesforce not connected")

    instance_url = (integration.get("metadata") or {}).get("instance_url", "")

    # Check if token is still valid (with 5-minute buffer)
    expires_at = integration.get("token_expires_at")
    if expires_at and expires_at > datetime.now(timezone.utc) + timedelta(minutes=5):
        return integration["access_token"], instance_url

    # Refresh
    settings = get_settings()
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            SALESFORCE_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": settings.salesforce_client_id,
                "client_secret": settings.salesforce_client_secret,
                "refresh_token": integration["refresh_token"],
            },
        )
        resp.raise_for_status()
        data = resp.json()

    new_instance_url = data.get("instance_url", instance_url)
    new_expires = datetime.now(timezone.utc) + timedelta(seconds=7200)
    await update_integration_tokens(
        user_id, "salesforce",
        access_token=data["access_token"],
        refresh_token=None,  # Salesforce doesn't rotate refresh tokens
        token_expires_at=new_expires,
    )
    return data["access_token"], new_instance_url


async def get_valid_token(user_id: int) -> tuple[str, str]:
    """Get a valid Salesforce access token + instance_url, refreshing if needed."""
    return await refresh_access_token(user_id)


async def fetch_accounts(user_id: int, limit: int = 100, offset: int = 0) -> dict:
    """Fetch accounts from Salesforce via SOQL.

    Returns {"records": [...], "totalSize": int, "done": bool}.
    """
    token, instance_url = await get_valid_token(user_id)
    query = (
        "SELECT Id, Name, Website, Industry FROM Account "
        "WHERE Website != null "
        f"ORDER BY Name ASC LIMIT {min(limit, 200)} OFFSET {offset}"
    )
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{instance_url}/services/data/v59.0/query",
            headers={"Authorization": f"Bearer {token}"},
            params={"q": query},
        )
        resp.raise_for_status()
        return resp.json()


async def _ensure_custom_fields(token: str, instance_url: str) -> None:
    """Create Auggie score custom fields on Account if they don't exist."""
    fields = [
        {"FullName": "Account.Auggie_Pain_Score__c", "Label": "Auggie Pain Score",
         "Type": "Number", "Precision": 3, "Scale": 0, "Description": "Pain score from Auggie research (0-100)"},
        {"FullName": "Account.Auggie_Fit_Score__c", "Label": "Auggie Fit Score",
         "Type": "Number", "Precision": 3, "Scale": 0, "Description": "Fit score from Auggie research (0-100)"},
        {"FullName": "Account.Auggie_Timing_Score__c", "Label": "Auggie Timing Score",
         "Type": "Number", "Precision": 3, "Scale": 0, "Description": "Timing score from Auggie research (0-100)"},
        {"FullName": "Account.Auggie_Composite_Score__c", "Label": "Auggie Composite Score",
         "Type": "Number", "Precision": 3, "Scale": 0, "Description": "Composite score from Auggie research (0-100)"},
    ]

    async with httpx.AsyncClient(timeout=15.0) as client:
        for field in fields:
            resp = await client.post(
                f"{instance_url}/services/data/v59.0/tooling/sobjects/CustomField",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"Metadata": field, "FullName": field["FullName"]},
            )
            if resp.status_code in (400, 409):
                continue  # Field already exists
            if resp.status_code >= 400:
                logger.warning("Failed to create Salesforce field %s: %s", field["FullName"], resp.text)


async def write_scores_to_salesforce(
    user_id: int,
    sf_account_id: str,
    pain_score: int | None,
    fit_score: int | None,
    timing_score: int | None,
    composite_score: int | None,
) -> bool:
    """Write Auggie scores back to a Salesforce account record."""
    token, instance_url = await get_valid_token(user_id)

    # Ensure custom fields exist (idempotent)
    await _ensure_custom_fields(token, instance_url)

    fields = {}
    if pain_score is not None:
        fields["Auggie_Pain_Score__c"] = pain_score
    if fit_score is not None:
        fields["Auggie_Fit_Score__c"] = fit_score
    if timing_score is not None:
        fields["Auggie_Timing_Score__c"] = timing_score
    if composite_score is not None:
        fields["Auggie_Composite_Score__c"] = composite_score

    if not fields:
        return True

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.patch(
            f"{instance_url}/services/data/v59.0/sobjects/Account/{sf_account_id}",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=fields,
        )
        if resp.status_code >= 400:
            logger.error("Salesforce writeback failed for account %s: %s", sf_account_id, resp.text)
            return False
        return True


async def write_list_scores_to_salesforce(user_id: int, list_source: dict, accounts: list[dict]) -> int:
    """Write scores for all completed accounts in a Salesforce-sourced list.

    Returns the number of successfully updated accounts.
    """
    sf_map = list_source.get("salesforce_account_map", {})
    if not sf_map:
        return 0

    updated = 0
    for account in accounts:
        if account.get("status") != "completed":
            continue
        company_url = account.get("company_url", "")
        sf_id = sf_map.get(company_url)
        if not sf_id:
            continue

        success = await write_scores_to_salesforce(
            user_id,
            sf_id,
            pain_score=account.get("pain_score"),
            fit_score=account.get("fit_score"),
            timing_score=account.get("timing_score"),
            composite_score=account.get("composite_score"),
        )
        if success:
            updated += 1

    return updated
