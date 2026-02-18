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


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------

class GoogleSheetsError(Exception):
    """Base error for all Google Sheets integration failures."""

    def __init__(self, code: str, message: str, status_code: int = 502):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class GoogleIntegrationMissing(GoogleSheetsError):
    def __init__(self):
        super().__init__("google_integration_missing", "Google Sheets is not connected. Connect it in Integrations.", 400)


class GoogleTokenRevoked(GoogleSheetsError):
    def __init__(self):
        super().__init__("google_token_revoked", "Google access was revoked. Please reconnect Google Sheets.", 401)


class GoogleTokenUnrecoverable(GoogleSheetsError):
    def __init__(self):
        super().__init__("google_token_expired_unrecoverable", "Google Sheets session expired. Please reconnect.", 401)


class GoogleScopeInsufficient(GoogleSheetsError):
    def __init__(self):
        super().__init__("google_scope_insufficient", "Permissions insufficient. Please reconnect with full access.", 403)


class GoogleSheetAccessDenied(GoogleSheetsError):
    def __init__(self):
        super().__init__("sheet_access_denied", "Access denied. Make sure the sheet is shared with your Google account.", 403)


class GoogleSheetNotFound(GoogleSheetsError):
    def __init__(self):
        super().__init__("sheet_not_found", "Spreadsheet not found. Check the URL and sharing settings.", 404)


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
    try:
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
            logger.info("OAuth token exchange succeeded")
            return resp.json()
    except httpx.HTTPStatusError as exc:
        logger.error("OAuth token exchange HTTP error", extra={"status_code": exc.response.status_code})
        raise GoogleSheetsError("oauth_token_exchange_failed", "Failed to complete authentication. Please try again.", 502) from exc
    except httpx.HTTPError as exc:
        logger.error("OAuth token exchange network error: %s", exc)
        raise GoogleSheetsError("oauth_token_exchange_failed", "Failed to complete authentication. Please try again.", 502) from exc


async def refresh_access_token(user_id: int) -> str:
    """Refresh Google access token if expired. Returns valid access token."""
    integration = await get_integration(user_id, "google_sheets")
    if not integration:
        raise GoogleIntegrationMissing()

    expires_at = integration.get("token_expires_at")
    if expires_at and expires_at > datetime.now(timezone.utc) + timedelta(minutes=5):
        return integration["access_token"]

    refresh_token = integration.get("refresh_token")
    if not refresh_token:
        logger.warning("No refresh token for user %s — token revoked or never granted offline access", user_id)
        raise GoogleTokenRevoked()

    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "refresh_token": refresh_token,
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        body = exc.response.text
        if "invalid_grant" in body:
            logger.warning("Google token revoked (invalid_grant) for user %s", user_id)
            raise GoogleTokenRevoked() from exc
        logger.error("Google token refresh HTTP error for user %s: %s", user_id, exc.response.status_code)
        raise GoogleTokenUnrecoverable() from exc
    except httpx.HTTPError as exc:
        logger.error("Google token refresh network error for user %s: %s", user_id, exc)
        raise GoogleTokenUnrecoverable() from exc

    new_expires = datetime.now(timezone.utc) + timedelta(seconds=data.get("expires_in", 3600))
    # Google only returns refresh_token on the initial consent grant; refresh
    # responses typically omit it.  Passing None here would erase the stored
    # token, causing future refreshes to fail with google_token_revoked.
    new_refresh = data.get("refresh_token") or refresh_token
    await update_integration_tokens(
        user_id, "google_sheets",
        access_token=data["access_token"],
        refresh_token=new_refresh,
        token_expires_at=new_expires,
    )
    logger.info("Google token refreshed for user %s", user_id)
    return data["access_token"]


def extract_spreadsheet_id(url: str) -> str | None:
    """Extract spreadsheet ID from a Google Sheets URL."""
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", url)
    return m.group(1) if m else None


async def _sheets_request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    token: str,
    user_id: int,
    operation: str,
    **kwargs,
) -> httpx.Response:
    """Make a Sheets API request with 401-retry and error classification."""
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bearer {token}"

    for attempt in range(2):
        resp = await getattr(client, method)(url, headers=headers, **kwargs)

        if resp.status_code == 401:
            if attempt == 0:
                logger.warning("Sheets API 401 on %s for user %s — refreshing token", operation, user_id)
                new_token = await refresh_access_token(user_id)
                headers["Authorization"] = f"Bearer {new_token}"
                continue
            logger.error("Sheets API 401 after refresh on %s for user %s", operation, user_id)
            raise GoogleTokenUnrecoverable()

        if resp.status_code == 403:
            body = resp.text
            if "insufficientPermissions" in body:
                raise GoogleScopeInsufficient()
            raise GoogleSheetAccessDenied()

        if resp.status_code == 404:
            raise GoogleSheetNotFound()

        if resp.status_code >= 400:
            logger.error("Sheets API %s error on %s for user %s", resp.status_code, operation, user_id)
            raise GoogleSheetsError("google_sheets_api_error", "Google Sheets API error. Please try again.", 502)

        return resp

    # Should not reach here, but satisfy type checker
    raise GoogleSheetsError("google_sheets_api_error", "Google Sheets API error. Please try again.", 502)


async def create_and_write_sheet(user_id: int, title: str, header: list[str], rows: list[list[str]]) -> str:
    """Create a new Google Spreadsheet, write header + rows, and return the spreadsheet URL."""
    token = await refresh_access_token(user_id)
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await _sheets_request(
            client, "post", SHEETS_API_BASE, token, user_id, "create_sheet",
            json={"properties": {"title": title}},
            headers={"Content-Type": "application/json"},
        )
        spreadsheet = resp.json()
        spreadsheet_id = spreadsheet["spreadsheetId"]
        spreadsheet_url = spreadsheet["spreadsheetUrl"]

        all_rows = [header] + rows
        await _sheets_request(
            client, "put",
            f"{SHEETS_API_BASE}/{spreadsheet_id}/values/Sheet1!A1",
            token, user_id, "write_sheet",
            params={"valueInputOption": "RAW"},
            json={"range": "Sheet1!A1", "majorDimension": "ROWS", "values": all_rows},
            headers={"Content-Type": "application/json"},
        )

    logger.info("Created and wrote sheet for user %s: %s", user_id, spreadsheet_url)
    return spreadsheet_url


async def fetch_sheet_rows(user_id: int, spreadsheet_id: str, sheet_range: str = "Sheet1") -> list[list[str]]:
    """Fetch rows from a Google Sheets spreadsheet via Sheets API v4."""
    token = await refresh_access_token(user_id)
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await _sheets_request(
            client, "get",
            f"{SHEETS_API_BASE}/{spreadsheet_id}/values/{sheet_range}",
            token, user_id, "fetch_rows",
        )
        data = resp.json()
    rows = data.get("values", [])
    logger.info("Fetched %d rows from sheet %s for user %s", len(rows), spreadsheet_id, user_id)
    return rows
