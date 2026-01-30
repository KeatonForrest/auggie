"""outreach.py - Outreach sales engagement integration: OAuth + push to sequences."""

import logging
from datetime import datetime, timezone, timedelta

import httpx

from config import get_settings
from database import (
    get_integration, upsert_integration, update_integration_tokens,
)

logger = logging.getLogger(__name__)

OUTREACH_AUTH_URL = "https://api.outreach.io/oauth/authorize"
OUTREACH_TOKEN_URL = "https://api.outreach.io/oauth/token"
OUTREACH_API_BASE = "https://api.outreach.io/api/v2"

SCOPES = "prospects.all sequences.all sequenceStates.all sequenceTemplates.all templates.all"


def get_authorize_url(state: str) -> str:
    """Build the Outreach OAuth authorization URL."""
    settings = get_settings()
    redirect_uri = f"{settings.app_url}/integrations/outreach/callback"
    return (
        f"{OUTREACH_AUTH_URL}"
        f"?response_type=code"
        f"&client_id={settings.outreach_client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&scope={SCOPES}"
        f"&state={state}"
    )


async def exchange_code(code: str) -> dict:
    """Exchange authorization code for tokens."""
    settings = get_settings()
    redirect_uri = f"{settings.app_url}/integrations/outreach/callback"
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            OUTREACH_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "client_id": settings.outreach_client_id,
                "client_secret": settings.outreach_client_secret,
                "redirect_uri": redirect_uri,
                "code": code,
            },
        )
        resp.raise_for_status()
        return resp.json()


async def refresh_access_token(user_id: int) -> str:
    """Refresh Outreach access token if expired. Returns valid access token."""
    integration = await get_integration(user_id, "outreach")
    if not integration:
        raise RuntimeError("Outreach not connected")

    expires_at = integration.get("token_expires_at")
    if expires_at and expires_at > datetime.now(timezone.utc) + timedelta(minutes=5):
        return integration["access_token"]

    settings = get_settings()
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            OUTREACH_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": settings.outreach_client_id,
                "client_secret": settings.outreach_client_secret,
                "redirect_uri": f"{settings.app_url}/integrations/outreach/callback",
                "refresh_token": integration["refresh_token"],
            },
        )
        resp.raise_for_status()
        data = resp.json()

    new_expires = datetime.now(timezone.utc) + timedelta(seconds=data.get("expires_in", 7200))
    await update_integration_tokens(
        user_id, "outreach",
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token", integration["refresh_token"]),
        token_expires_at=new_expires,
    )
    return data["access_token"]


async def get_valid_token(user_id: int) -> str:
    """Get a valid Outreach access token, refreshing if needed."""
    return await refresh_access_token(user_id)


async def list_sequences(user_id: int) -> list[dict]:
    """List active sequences from Outreach."""
    token = await get_valid_token(user_id)
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{OUTREACH_API_BASE}/sequences",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/vnd.api+json"},
            params={"filter[enabled]": "true", "page[size]": 50},
        )
        resp.raise_for_status()
        data = resp.json()
    return [
        {"id": s["id"], "name": s["attributes"].get("name", "")}
        for s in data.get("data", [])
    ]


async def _create_sequence_with_emails(
    token: str,
    company_name: str,
    emails: list[dict],
) -> int | None:
    """Create an Outreach sequence with Auggie-generated email steps.

    Returns the sequence ID, or None on failure.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        # 1. Create the sequence
        seq_resp = await client.post(
            f"{OUTREACH_API_BASE}/sequences",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/vnd.api+json"},
            json={
                "data": {
                    "type": "sequence",
                    "attributes": {
                        "name": f"Auggie – {company_name}",
                        "sequenceType": "standard",
                        "enabled": True,
                    },
                }
            },
        )
        if seq_resp.status_code >= 400:
            logger.warning("Outreach sequence create failed: %s", seq_resp.text[:200])
            return None
        sequence_id = seq_resp.json()["data"]["id"]

        # 2. Add email steps
        for i, email in enumerate(emails):
            # Create a template for this step
            tpl_resp = await client.post(
                f"{OUTREACH_API_BASE}/templates",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/vnd.api+json"},
                json={
                    "data": {
                        "type": "template",
                        "attributes": {
                            "name": f"Auggie – {company_name} – Email {email.get('email_number', i + 1)}",
                            "subject": email.get("subject", ""),
                            "bodyHtml": f"<p>{_plain_to_html(email.get('body', ''))}</p>",
                            "toRecipients": ["{{email}}"],
                        },
                    }
                },
            )
            if tpl_resp.status_code >= 400:
                logger.warning("Outreach template create failed: %s", tpl_resp.text[:200])
                continue
            template_id = tpl_resp.json()["data"]["id"]

            # Create sequence step linked to template
            step_resp = await client.post(
                f"{OUTREACH_API_BASE}/sequenceSteps",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/vnd.api+json"},
                json={
                    "data": {
                        "type": "sequenceStep",
                        "attributes": {
                            "stepType": "auto_email",
                            "order": i + 1,
                            "interval": 3 if i > 0 else 0,  # 3-day gap between follow-ups
                        },
                        "relationships": {
                            "sequence": {"data": {"type": "sequence", "id": sequence_id}},
                        },
                    }
                },
            )
            if step_resp.status_code >= 400:
                logger.warning("Outreach step create failed: %s", step_resp.text[:200])
                continue
            step_id = step_resp.json()["data"]["id"]

            # Link template to step
            await client.post(
                f"{OUTREACH_API_BASE}/sequenceTemplates",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/vnd.api+json"},
                json={
                    "data": {
                        "type": "sequenceTemplate",
                        "attributes": {"isReply": i > 0},
                        "relationships": {
                            "template": {"data": {"type": "template", "id": template_id}},
                            "sequenceStep": {"data": {"type": "sequenceStep", "id": step_id}},
                        },
                    }
                },
            )

    return sequence_id


def _plain_to_html(text: str) -> str:
    """Convert plain text to simple HTML paragraphs."""
    import html
    escaped = html.escape(text)
    return escaped.replace("\n\n", "</p><p>").replace("\n", "<br>")


async def push_sequences_to_outreach(
    user_id: int,
    accounts: list[dict],
    drafts_by_account: dict[int, list[dict]],
) -> dict:
    """Create Outreach sequences with Auggie-generated email content (no contacts).

    Creates one sequence per account. Users assign their own prospects in Outreach.

    Returns {"sequences_created": int, "skipped": int, "errors": int}.
    """
    token = await get_valid_token(user_id)
    sequences_created = 0
    skipped = 0
    errors = 0
    created_ids = []

    for account in accounts:
        emails = drafts_by_account.get(account["id"])
        if not emails:
            skipped += 1
            continue

        created_id = await _create_sequence_with_emails(
            token, account.get("company_name", "Unknown"), emails,
        )
        if created_id:
            sequences_created += 1
            created_ids.append(created_id)
        else:
            errors += 1

    return {
        "sequences_created": sequences_created,
        "skipped": skipped,
        "errors": errors,
        "created_ids": created_ids,
    }
