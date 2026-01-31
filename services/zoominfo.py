"""zoominfo.py - ZoomInfo data integration: OAuth (PKCE via Okta) + company search."""

import base64
import hashlib
import logging
import secrets
from datetime import datetime, timezone, timedelta

import httpx

from config import get_settings
from database import (
    get_integration, upsert_integration, update_integration_tokens,
)

logger = logging.getLogger(__name__)

ZOOMINFO_LOGIN_URL = "https://login.zoominfo.com/"
ZOOMINFO_TOKEN_URL = "https://okta-login.zoominfo.com/oauth2/default/v1/token"
ZOOMINFO_API_BASE = "https://api.zoominfo.com/gtm/data/v1"

SCOPE = "api:data:company"


def generate_pkce_pair() -> tuple[str, str]:
    """Generate PKCE code_verifier and code_challenge (S256)."""
    code_verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


def get_authorize_url(state: str, code_challenge: str) -> str:
    """Build the ZoomInfo OAuth authorization URL with PKCE."""
    settings = get_settings()
    redirect_uri = f"{settings.app_url}/integrations/zoominfo/callback"
    return (
        f"{ZOOMINFO_LOGIN_URL}"
        f"?response_type=code"
        f"&client_id={settings.zoominfo_client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&scope={SCOPE}"
        f"&state={state}"
        f"&code_challenge={code_challenge}"
        f"&code_challenge_method=S256"
    )


async def exchange_code(code: str, code_verifier: str) -> dict:
    """Exchange authorization code for tokens at Okta token endpoint."""
    settings = get_settings()
    redirect_uri = f"{settings.app_url}/integrations/zoominfo/callback"
    credentials = base64.b64encode(
        f"{settings.zoominfo_client_id}:{settings.zoominfo_client_secret}".encode()
    ).decode()
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            ZOOMINFO_TOKEN_URL,
            headers={"Authorization": f"Basic {credentials}"},
            data={
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
                "code": code,
                "code_verifier": code_verifier,
            },
        )
        resp.raise_for_status()
        return resp.json()


async def refresh_access_token(user_id: int) -> str:
    """Refresh ZoomInfo access token if expired. Returns valid access token."""
    integration = await get_integration(user_id, "zoominfo")
    if not integration:
        raise RuntimeError("ZoomInfo not connected")

    expires_at = integration.get("token_expires_at")
    if expires_at and expires_at > datetime.now(timezone.utc) + timedelta(minutes=5):
        return integration["access_token"]

    settings = get_settings()
    credentials = base64.b64encode(
        f"{settings.zoominfo_client_id}:{settings.zoominfo_client_secret}".encode()
    ).decode()
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            ZOOMINFO_TOKEN_URL,
            headers={"Authorization": f"Basic {credentials}"},
            data={
                "grant_type": "refresh_token",
                "refresh_token": integration["refresh_token"],
            },
        )
        resp.raise_for_status()
        data = resp.json()

    new_expires = datetime.now(timezone.utc) + timedelta(seconds=data.get("expires_in", 86400))
    await update_integration_tokens(
        user_id, "zoominfo",
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token", integration["refresh_token"]),
        token_expires_at=new_expires,
    )
    return data["access_token"]


async def search_companies(user_id: int, query: str, page: int = 1) -> list[dict]:
    """Search companies via ZoomInfo API. Returns simplified company list."""
    token = await refresh_access_token(user_id)
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{ZOOMINFO_API_BASE}/companies/search",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/vnd.api+json",
            },
            json={
                "filter": {"companyName": query},
                "pageNumber": page,
                "pageSize": 25,
            },
        )
        resp.raise_for_status()
        data = resp.json()

    results = []
    for c in data.get("data", []):
        results.append({
            "id": c.get("id"),
            "name": c.get("companyName", ""),
            "website": c.get("website", ""),
            "employeeCount": c.get("employeeCount"),
            "revenue": c.get("revenue"),
            "city": c.get("city", ""),
            "state": c.get("state", ""),
            "country": c.get("country", ""),
        })
    return results
