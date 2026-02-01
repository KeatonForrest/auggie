"""gong_engage.py - Gong Engage integration: OAuth + push sequences to flows."""

import html
import logging
from datetime import datetime, timezone, timedelta

import httpx

from config import get_settings
from database import (
    get_integration, upsert_integration, update_integration_tokens,
    update_list_account_pushed,
)

logger = logging.getLogger(__name__)

GONG_AUTH_URL = "https://app.gong.io/oauth2/authorize"
GONG_TOKEN_URL = "https://app.gong.io/oauth2/token"
GONG_API_BASE = "https://api.gong.io"

SCOPES = "api:flows:read api:flows:write"


def get_authorize_url(state: str) -> str:
    """Build the Gong Engage OAuth authorization URL."""
    settings = get_settings()
    redirect_uri = f"{settings.app_url}/integrations/gong_engage/callback"
    return (
        f"{GONG_AUTH_URL}"
        f"?response_type=code"
        f"&client_id={settings.gong_engage_client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&scope={SCOPES}"
        f"&state={state}"
    )


async def exchange_code(code: str) -> dict:
    """Exchange authorization code for tokens."""
    settings = get_settings()
    redirect_uri = f"{settings.app_url}/integrations/gong_engage/callback"
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            GONG_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "client_id": settings.gong_engage_client_id,
                "client_secret": settings.gong_engage_client_secret,
                "redirect_uri": redirect_uri,
                "code": code,
            },
        )
        resp.raise_for_status()
        return resp.json()


async def refresh_access_token(user_id: int) -> str:
    """Refresh Gong Engage access token if expired. Returns valid access token."""
    integration = await get_integration(user_id, "gong_engage")
    if not integration:
        raise RuntimeError("Gong Engage not connected")

    expires_at = integration.get("token_expires_at")
    if expires_at and expires_at > datetime.now(timezone.utc) + timedelta(minutes=5):
        return integration["access_token"]

    settings = get_settings()
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            GONG_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": settings.gong_engage_client_id,
                "client_secret": settings.gong_engage_client_secret,
                "redirect_uri": f"{settings.app_url}/integrations/gong_engage/callback",
                "refresh_token": integration["refresh_token"],
            },
        )
        resp.raise_for_status()
        data = resp.json()

    new_expires = datetime.now(timezone.utc) + timedelta(seconds=data.get("expires_in", 7200))
    await update_integration_tokens(
        user_id, "gong_engage",
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token", integration["refresh_token"]),
        token_expires_at=new_expires,
    )
    return data["access_token"]


async def get_valid_token(user_id: int) -> str:
    """Get a valid Gong Engage access token, refreshing if needed."""
    return await refresh_access_token(user_id)


async def list_flows(user_id: int) -> list[dict]:
    """List flows from Gong Engage."""
    token = await get_valid_token(user_id)
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{GONG_API_BASE}/v2/flows",
            headers={"Authorization": f"Bearer {token}"},
        )
        resp.raise_for_status()
        data = resp.json()
    return [
        {"id": f["id"], "name": f.get("name", "")}
        for f in data.get("flows", [])
    ]


def _plain_to_html(text: str) -> str:
    """Convert plain text to simple HTML paragraphs."""
    escaped = html.escape(text)
    return escaped.replace("\n\n", "</p><p>").replace("\n", "<br>")


async def push_sequences_to_gong_engage(
    user_id: int,
    flow_id: str,
    flow_owner_email: str,
    accounts: list[dict],
    drafts_by_account: dict[int, list[dict]],
) -> dict:
    """Assign prospects to a Gong Engage flow with content overrides.

    Each account's email drafts become step content overrides on the flow.
    Prospects are batched up to 200 per request.

    Returns {"prospects_assigned": int, "skipped": int, "errors": int}.
    """
    token = await get_valid_token(user_id)
    prospects_assigned = 0
    skipped = 0
    errors = 0

    # Build prospect assignments
    assignments = []
    account_id_map = {}  # track which assignment index -> account id
    for account in accounts:
        emails = drafts_by_account.get(account["id"])
        if not emails:
            skipped += 1
            continue

        # Build content overrides: map each email to a flow step
        content_overrides = []
        for i, email in enumerate(emails):
            content_overrides.append({
                "stepIndex": i,
                "subject": email.get("subject", ""),
                "body": f"<p>{_plain_to_html(email.get('body', ''))}</p>",
            })

        assignment = {
            "prospectId": account.get("company_url", ""),
            "contentOverrides": content_overrides,
        }
        assignments.append(assignment)
        account_id_map[len(assignments) - 1] = account["id"]

    if not assignments:
        return {"prospects_assigned": 0, "skipped": skipped, "errors": 0}

    # Batch in groups of 200
    async with httpx.AsyncClient(timeout=30.0) as client:
        for batch_start in range(0, len(assignments), 200):
            batch = assignments[batch_start:batch_start + 200]
            try:
                resp = await client.post(
                    f"{GONG_API_BASE}/v2/flows/prospects/assign",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "flowId": flow_id,
                        "flowInstanceOwnerEmail": flow_owner_email,
                        "prospects": batch,
                    },
                )
                if resp.status_code < 400:
                    count = len(batch)
                    prospects_assigned += count
                    # Mark accounts as pushed
                    for j in range(len(batch)):
                        aid = account_id_map.get(batch_start + j)
                        if aid:
                            await update_list_account_pushed(aid, "gong_engage", {
                                "flow_id": flow_id,
                                "pushed_at": datetime.now(timezone.utc).isoformat(),
                            })
                else:
                    logger.warning("Gong Engage assign failed: %s", resp.text[:200])
                    errors += len(batch)
            except Exception as e:
                logger.error("Gong Engage assign error: %s", e)
                errors += len(batch)

    return {
        "prospects_assigned": prospects_assigned,
        "skipped": skipped,
        "errors": errors,
    }
