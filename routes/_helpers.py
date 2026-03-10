"""Shared utilities used across route modules."""

import logging
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from config import get_settings
from database import upsert_integration
from services.materials import MaterialsService
from utils.icp import BUYER_VERTICALS, LEGACY_VERTICAL_MAP, normalize_verticals
from utils.personas import parse_personas_string, build_target_titles

# Backwards-compatible export for tests / older imports.
_LEGACY_VERTICAL_MAP = LEGACY_VERTICAL_MAP

logger = logging.getLogger(__name__)
settings = get_settings()
templates = Jinja2Templates(directory="templates")

# Lazy-initialized materials service
materials_service = None


def get_materials_service():
    """Get or create materials service (lazy init)."""
    global materials_service
    if materials_service is None and settings.materials_enabled:
        materials_service = MaterialsService()
    return materials_service


def normalize_url(url: str) -> str:
    """Add https:// if no protocol specified. For non-research URLs."""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


# Seller product categories (single-select — describes what the seller builds)
SELLER_PRODUCT_CATEGORIES = [
    "Fintech", "HealthTech", "MarTech", "ConstructionTech", "EdTech",
    "PropTech", "InsurTech", "LegalTech", "HRTech", "Cybersecurity / IT",
    "DevTools / Infra", "E-commerce Tech", "Supply Chain / Logistics Tech",
    "GovTech", "TravelTech", "MediaTech", "Other / Cross-industry",
]

def _build_target_titles(user: dict) -> list[str]:
    """Build a list of target job titles from user's ICP settings."""
    return build_target_titles(user.get("target_personas") or "", max_titles=5)


# ---------------------------------------------------------------------------
# Generic OAuth connect / callback / API-key helpers
# ---------------------------------------------------------------------------

async def _oauth_connect(request: Request, provider: str, get_authorize_url_fn):
    """Generic OAuth redirect: generate state, store in session, redirect."""
    state = secrets.token_urlsafe(24)
    request.session[f"_{provider}_state_"] = state
    url = get_authorize_url_fn(state)
    return RedirectResponse(url=url)


async def _oauth_callback(
    request: Request,
    user: dict,
    provider: str,
    exchange_code_fn,
    expires_in_default: int = 7200,
    metadata_fn=None,
):
    """Generic OAuth callback: verify state, exchange code, upsert integration."""
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    expected_state = request.session.get(f"_{provider}_state_")

    if not code:
        logger.warning("OAuth callback missing code", extra={"event_type": "oauth_callback_error", "provider": provider, "user_id": user["id"]})
        raise HTTPException(status_code=400, detail={"code": "oauth_callback_missing_code", "message": "Authorization was not granted. Please try again."})

    if not expected_state or state != expected_state:
        logger.warning("OAuth callback state mismatch", extra={"event_type": "oauth_callback_error", "provider": provider, "user_id": user["id"]})
        raise HTTPException(status_code=400, detail={"code": "oauth_state_invalid", "message": "OAuth session expired. Please try connecting again."})

    request.session.pop(f"_{provider}_state_", None)

    try:
        token_data = await exchange_code_fn(code)
    except Exception as exc:
        logger.error("OAuth token exchange failed for %s", provider, extra={"event_type": "oauth_callback_error", "provider": provider, "user_id": user["id"]}, exc_info=True)
        raise HTTPException(status_code=502, detail={"code": "oauth_token_exchange_failed", "message": "Failed to complete authentication. Please try again."}) from exc

    expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=token_data.get("expires_in", expires_in_default)
    )

    kwargs = dict(
        user_id=user["id"],
        provider=provider,
        access_token=token_data["access_token"],
        refresh_token=token_data.get("refresh_token"),
        token_expires_at=expires_at,
    )
    if metadata_fn:
        kwargs["metadata"] = metadata_fn(token_data)

    await upsert_integration(**kwargs)
    logger.info("OAuth integration connected", extra={"event_type": "oauth_integration_connected", "provider": provider, "user_id": user["id"]})
    return RedirectResponse(url="/integrations", status_code=302)


# ---------------------------------------------------------------------------
# Retry helper
# ---------------------------------------------------------------------------
