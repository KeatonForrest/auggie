"""salesloft.py - SalesLoft sales engagement integration: OAuth + push to cadences."""

import logging
from datetime import datetime, timezone, timedelta

import httpx

from config import get_settings
from database import (
    get_integration, upsert_integration, update_integration_tokens,
)

logger = logging.getLogger(__name__)

SALESLOFT_AUTH_URL = "https://accounts.salesloft.com/oauth/authorize"
SALESLOFT_TOKEN_URL = "https://accounts.salesloft.com/oauth/token"
SALESLOFT_API_BASE = "https://api.salesloft.com/v2"


def get_authorize_url(state: str) -> str:
    """Build the SalesLoft OAuth authorization URL."""
    settings = get_settings()
    redirect_uri = f"{settings.app_url}/integrations/salesloft/callback"
    return (
        f"{SALESLOFT_AUTH_URL}"
        f"?response_type=code"
        f"&client_id={settings.salesloft_client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&state={state}"
    )


async def exchange_code(code: str) -> dict:
    """Exchange authorization code for tokens."""
    settings = get_settings()
    redirect_uri = f"{settings.app_url}/integrations/salesloft/callback"
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            SALESLOFT_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "client_id": settings.salesloft_client_id,
                "client_secret": settings.salesloft_client_secret,
                "redirect_uri": redirect_uri,
                "code": code,
            },
        )
        resp.raise_for_status()
        return resp.json()


async def refresh_access_token(user_id: int) -> str:
    """Refresh SalesLoft access token if expired. Returns valid access token."""
    integration = await get_integration(user_id, "salesloft")
    if not integration:
        raise RuntimeError("SalesLoft not connected")

    expires_at = integration.get("token_expires_at")
    if expires_at and expires_at > datetime.now(timezone.utc) + timedelta(minutes=5):
        return integration["access_token"]

    settings = get_settings()
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            SALESLOFT_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": settings.salesloft_client_id,
                "client_secret": settings.salesloft_client_secret,
                "refresh_token": integration["refresh_token"],
            },
        )
        resp.raise_for_status()
        data = resp.json()

    new_expires = datetime.now(timezone.utc) + timedelta(seconds=data.get("expires_in", 7200))
    await update_integration_tokens(
        user_id, "salesloft",
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token", integration["refresh_token"]),
        token_expires_at=new_expires,
    )
    return data["access_token"]


async def get_valid_token(user_id: int) -> str:
    """Get a valid SalesLoft access token, refreshing if needed."""
    return await refresh_access_token(user_id)


async def list_cadences(user_id: int) -> list[dict]:
    """List cadences from SalesLoft."""
    token = await get_valid_token(user_id)
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{SALESLOFT_API_BASE}/cadences",
            headers={"Authorization": f"Bearer {token}"},
            params={"per_page": 50},
        )
        resp.raise_for_status()
        data = resp.json()
    return [
        {"id": c["id"], "name": c.get("name", "")}
        for c in data.get("data", [])
    ]


async def _create_cadence_with_emails(
    token: str,
    company_name: str,
    emails: list[dict],
) -> int | None:
    """Create a SalesLoft cadence with Auggie-generated email steps.

    Returns the cadence ID, or None on failure.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        # 1. Create the cadence
        cadence_resp = await client.post(
            f"{SALESLOFT_API_BASE}/cadences",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={
                "name": f"Auggie – {company_name}",
                "cadence_function": "outbound",
            },
        )
        if cadence_resp.status_code >= 400:
            logger.warning("SalesLoft cadence create failed: %s", cadence_resp.text[:200])
            return None
        cadence_id = cadence_resp.json()["data"]["id"]

        # 2. Add email steps
        for i, email in enumerate(emails):
            step_resp = await client.post(
                f"{SALESLOFT_API_BASE}/steps",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={
                    "cadence_id": cadence_id,
                    "day": 1 + (i * 3),  # Day 1, 4, 7
                    "step_type": "email",
                    "name": f"Email {email.get('email_number', i + 1)}",
                    "details": {
                        "email_template": {
                            "subject": email.get("subject", ""),
                            "body": email.get("body", ""),
                            "is_reply": i > 0,
                        },
                    },
                },
            )
            if step_resp.status_code >= 400:
                logger.warning("SalesLoft step create failed: %s", step_resp.text[:200])

    return cadence_id


async def push_sequences_to_salesloft(
    user_id: int,
    accounts: list[dict],
    drafts_by_account: dict[int, list[dict]],
) -> dict:
    """Create SalesLoft cadences with Auggie-generated email content (no contacts).

    Creates one cadence per account. Users assign their own people in SalesLoft.

    Returns {"cadences_created": int, "skipped": int, "errors": int}.
    """
    token = await get_valid_token(user_id)
    cadences_created = 0
    skipped = 0
    errors = 0

    for account in accounts:
        emails = drafts_by_account.get(account["id"])
        if not emails:
            skipped += 1
            continue

        created_id = await _create_cadence_with_emails(
            token, account.get("company_name", "Unknown"), emails,
        )
        if created_id:
            cadences_created += 1
        else:
            errors += 1

    return {"cadences_created": cadences_created, "skipped": skipped, "errors": errors}
