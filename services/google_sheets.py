"""google_sheets.py - Google Sheets integration: OAuth, spreadsheet import."""

import logging
import re
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode

import httpx

from config import get_settings
from database import (
    get_integration, update_integration_tokens,
)

logger = logging.getLogger(__name__)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
SHEETS_API_BASE = "https://sheets.googleapis.com/v4/spreadsheets"

SCOPES = "https://www.googleapis.com/auth/spreadsheets"


def get_authorize_url(state: str) -> str:
    """Build the Google OAuth authorization URL with Sheets scope."""
    settings = get_settings()
    redirect_uri = f"{settings.app_url}/integrations/google_sheets/callback"
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPES,
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


async def exchange_code(code: str) -> dict:
    """Exchange authorization code for tokens."""
    settings = get_settings()
    redirect_uri = f"{settings.app_url}/integrations/google_sheets/callback"
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": redirect_uri,
                "code": code,
            },
        )
        resp.raise_for_status()
        return resp.json()


async def refresh_access_token(user_id: int) -> str:
    """Refresh Google access token if expired. Returns valid access token."""
    integration = await get_integration(user_id, "google_sheets")
    if not integration:
        raise RuntimeError("Google Sheets not connected")

    expires_at = integration.get("token_expires_at")
    if expires_at and expires_at > datetime.now(timezone.utc) + timedelta(minutes=5):
        return integration["access_token"]

    settings = get_settings()
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "refresh_token": integration["refresh_token"],
            },
        )
        resp.raise_for_status()
        data = resp.json()

    new_expires = datetime.now(timezone.utc) + timedelta(seconds=data.get("expires_in", 3600))
    await update_integration_tokens(
        user_id, "google_sheets",
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token"),
        token_expires_at=new_expires,
    )
    return data["access_token"]


def extract_spreadsheet_id(url: str) -> str | None:
    """Extract spreadsheet ID from a Google Sheets URL."""
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", url)
    return m.group(1) if m else None


async def create_and_write_sheet(user_id: int, title: str, header: list[str], rows: list[list[str]]) -> str:
    """Create a new Google Spreadsheet, write header + rows, and return the spreadsheet URL."""
    token = await refresh_access_token(user_id)
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Create spreadsheet
        resp = await client.post(
            SHEETS_API_BASE,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"properties": {"title": title}},
        )
        resp.raise_for_status()
        spreadsheet = resp.json()
        spreadsheet_id = spreadsheet["spreadsheetId"]
        spreadsheet_url = spreadsheet["spreadsheetUrl"]

        # Write data
        all_rows = [header] + rows
        resp = await client.put(
            f"{SHEETS_API_BASE}/{spreadsheet_id}/values/Sheet1!A1",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            params={"valueInputOption": "RAW"},
            json={"range": "Sheet1!A1", "majorDimension": "ROWS", "values": all_rows},
        )
        resp.raise_for_status()

    return spreadsheet_url


async def fetch_sheet_rows(user_id: int, spreadsheet_id: str, sheet_range: str = "Sheet1") -> list[list[str]]:
    """Fetch rows from a Google Sheets spreadsheet via Sheets API v4."""
    token = await refresh_access_token(user_id)
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"{SHEETS_API_BASE}/{spreadsheet_id}/values/{sheet_range}",
            headers={"Authorization": f"Bearer {token}"},
        )
        resp.raise_for_status()
        data = resp.json()
    return data.get("values", [])
