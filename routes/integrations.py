"""Integration routes: OAuth + API-key connect/disconnect/callback/import for all providers."""

from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse

from auth import require_auth, require_onboarding
from config import get_settings
from database import (
    get_user_usage, get_user_integrations, get_integration,
    delete_integration, upsert_integration,
)
from routes._helpers import (
    templates, logger,
    _oauth_connect, _oauth_callback,
)
from routes.schemas import ApiKeyConnectRequest, SlackConnectRequest
from services.google_sheets import get_authorize_url as gsheets_authorize_url, exchange_code as gsheets_exchange_code
from services.notifications import validate_webhook_url, send_slack_notification, validate_teams_webhook_url, send_teams_notification

settings = get_settings()
router = APIRouter()


# ==========================================================================
# Integrations page
# ==========================================================================

@router.get("/integrations", response_class=HTMLResponse)
async def integrations_page(request: Request, user: dict = Depends(require_onboarding)):
    """Integration management page."""
    integrations = await get_user_integrations(user["id"])
    integration_map = {i["provider"]: i for i in integrations}
    usage = await get_user_usage(user["id"])
    return templates.TemplateResponse(
        request,
        "integrations.html",
        {
            "user": user,
            "integrations": integration_map,
            "credits": usage.get("bonus_credits", 0) / 100,
            "is_admin": usage.get("is_admin", False),
        }
    )


# ==========================================================================
# Deprecated provider disconnect (safety valve — no UI, tokens only)
# ==========================================================================

_DEPRECATED_PROVIDERS = frozenset({
    "hubspot", "salesforce", "outreach", "salesloft", "gong_engage",
    "zoominfo", "instantly", "smartlead", "pdl", "lusha", "cognism",
})


@router.post("/integrations/{provider}/disconnect")
async def deprecated_disconnect(provider: str, request: Request, user: dict = Depends(require_auth)):
    """Disconnect a deprecated integration. Allows cleanup of legacy tokens."""
    if provider not in _DEPRECATED_PROVIDERS:
        raise HTTPException(status_code=404, detail="Not found")
    await delete_integration(user["id"], provider)
    return RedirectResponse(url="/integrations", status_code=303)


# ==========================================================================
# Slack
# ==========================================================================

@router.post("/integrations/slack/connect")
async def slack_connect(request: Request, user: dict = Depends(require_auth)):
    """Save Slack webhook URL after validation."""
    body = SlackConnectRequest(**(await request.json()))
    webhook_url = body.webhook_url.strip()
    if not webhook_url:
        raise HTTPException(status_code=400, detail="Webhook URL is required")

    valid = await validate_webhook_url(webhook_url)
    if not valid:
        raise HTTPException(status_code=400, detail="Invalid Slack webhook URL — test message failed")

    await upsert_integration(user_id=user["id"], provider="slack", access_token=webhook_url)
    return JSONResponse({"success": True})


@router.post("/integrations/slack/disconnect")
async def slack_disconnect(request: Request, user: dict = Depends(require_auth)):
    """Disconnect Slack integration."""
    await delete_integration(user["id"], "slack")
    return RedirectResponse(url="/integrations", status_code=303)


@router.post("/integrations/slack/test")
async def slack_test(request: Request, user: dict = Depends(require_auth)):
    """Send a test Slack notification."""
    integration = await get_integration(user["id"], "slack")
    if not integration:
        raise HTTPException(status_code=400, detail="Slack not connected")

    ok = await send_slack_notification(
        integration["access_token"],
        "research_complete",
        {
            "company_name": "Test Company",
            "pain_score": 85,
            "composite_score": 78,
            "doc_url": f"{settings.app_url}/",
        },
    )

    if not ok:
        raise HTTPException(status_code=502, detail="Failed to send test message")

    return JSONResponse({"success": True})


# ==========================================================================
# Microsoft Teams
# ==========================================================================

@router.post("/integrations/teams/connect")
async def teams_connect(request: Request, user: dict = Depends(require_auth)):
    """Save Teams webhook URL after validation."""
    body = SlackConnectRequest(**(await request.json()))
    webhook_url = body.webhook_url.strip()
    if not webhook_url:
        raise HTTPException(status_code=400, detail="Webhook URL is required")

    valid = await validate_teams_webhook_url(webhook_url)
    if not valid:
        raise HTTPException(status_code=400, detail="Invalid Teams webhook URL — test message failed")

    await upsert_integration(user_id=user["id"], provider="teams", access_token=webhook_url)
    return JSONResponse({"success": True})


@router.post("/integrations/teams/disconnect")
async def teams_disconnect(request: Request, user: dict = Depends(require_auth)):
    """Disconnect Teams integration."""
    await delete_integration(user["id"], "teams")
    return RedirectResponse(url="/integrations", status_code=303)


@router.post("/integrations/teams/test")
async def teams_test(request: Request, user: dict = Depends(require_auth)):
    """Send a test Teams notification."""
    integration = await get_integration(user["id"], "teams")
    if not integration:
        raise HTTPException(status_code=400, detail="Teams not connected")

    ok = await send_teams_notification(
        integration["access_token"],
        "research_complete",
        {
            "company_name": "Test Company",
            "pain_score": 85,
            "composite_score": 78,
            "doc_url": f"{settings.app_url}/",
        },
    )

    if not ok:
        raise HTTPException(status_code=502, detail="Failed to send test message")

    return JSONResponse({"success": True})


# ==========================================================================
# Google Sheets
# ==========================================================================

@router.get("/integrations/google_sheets/connect")
async def google_sheets_connect(request: Request, user: dict = Depends(require_auth)):
    """Redirect to Google OAuth for Sheets access."""
    logger.info("Google Sheets connect initiated", extra={"event_type": "google_sheets_connect", "user_id": user["id"]})
    return await _oauth_connect(request, "google_sheets", gsheets_authorize_url)


@router.get("/integrations/google_sheets/callback")
async def google_sheets_callback(request: Request, user: dict = Depends(require_auth)):
    """Handle Google Sheets OAuth callback."""
    return await _oauth_callback(
        request, user, "google_sheets", gsheets_exchange_code,
        expires_in_default=3600,
    )


@router.post("/integrations/google_sheets/disconnect")
async def google_sheets_disconnect(request: Request, user: dict = Depends(require_auth)):
    """Disconnect Google Sheets integration."""
    await delete_integration(user["id"], "google_sheets")
    logger.info("Google Sheets disconnected", extra={"event_type": "google_sheets_disconnect", "user_id": user["id"]})
    return RedirectResponse(url="/integrations", status_code=303)


# ==========================================================================
# Integration landing pages
# ==========================================================================

@router.get("/integrations/clay", response_class=HTMLResponse)
async def integrations_clay(request: Request):
    """Clay integration landing page for marketplace listing."""
    from auth import get_current_user
    user = await get_current_user(request)
    return templates.TemplateResponse(request, "integrations_clay.html", {"user": user})


@router.get("/integrations/make", response_class=HTMLResponse)
async def integrations_make(request: Request):
    """Make integration setup guide."""
    from auth import get_current_user
    user = await get_current_user(request)
    return templates.TemplateResponse(request, "integrations_make.html", {"user": user})


@router.get("/integrations/n8n", response_class=HTMLResponse)
async def integrations_n8n(request: Request):
    """n8n integration setup guide."""
    from auth import get_current_user
    user = await get_current_user(request)
    return templates.TemplateResponse(request, "integrations_n8n.html", {"user": user})


@router.get("/integrations/zapier", response_class=HTMLResponse)
async def integrations_zapier(request: Request):
    """Zapier integration setup guide."""
    from auth import get_current_user
    user = await get_current_user(request)
    return templates.TemplateResponse(request, "integrations_zapier.html", {"user": user})
