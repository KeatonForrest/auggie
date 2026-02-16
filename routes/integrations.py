"""Integration routes: OAuth + API-key connect/disconnect/callback/import for all providers."""

import logging

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
    _oauth_connect, _oauth_callback, _apikey_connect, _run_crm_import,
)
from routes.integrations_constants import DEPRECATION_MESSAGE, DEPRECATED_PROVIDERS, DEPRECATED_PROVIDER_NAMES
from routes.schemas import ApiKeyConnectRequest, ApolloImportRequest, SlackConnectRequest
from services.google_sheets import get_authorize_url as gsheets_authorize_url, exchange_code as gsheets_exchange_code
from services.apollo import validate_integration_api_key as apollo_validate
from services.notifications import validate_webhook_url, send_slack_notification, validate_teams_webhook_url, send_teams_notification

settings = get_settings()
router = APIRouter()


def _deprecated_response(provider: str) -> JSONResponse:
    """Return a 410 Gone response for deprecated integrations."""
    return JSONResponse(
        status_code=410,
        content={"error": {"code": "provider_deprecated", "message": f"{provider}: {DEPRECATION_MESSAGE}"}},
    )


# ==========================================================================
# Integrations page
# ==========================================================================

@router.get("/integrations", response_class=HTMLResponse)
async def integrations_page(request: Request, user: dict = Depends(require_onboarding)):
    """Integration management page."""
    integrations = await get_user_integrations(user["id"])
    integration_map = {i["provider"]: i for i in integrations}
    usage = await get_user_usage(user["id"])
    deprecated_connected = [
        {"provider": p, "name": DEPRECATED_PROVIDER_NAMES.get(p, p)}
        for p in integration_map if p in DEPRECATED_PROVIDERS
    ]
    return templates.TemplateResponse(
        request,
        "integrations.html",
        {
            "user": user,
            "integrations": integration_map,
            "credits": usage.get("bonus_credits", 0) / 100,
            "is_admin": usage.get("is_admin", False),
            "deprecated_integrations": deprecated_connected,
        }
    )


# ==========================================================================
# HubSpot
# ==========================================================================

@router.get("/integrations/hubspot/connect")
async def hubspot_connect(request: Request, user: dict = Depends(require_auth)):
    """Redirect to HubSpot OAuth."""
    return _deprecated_response("hubspot")


@router.get("/integrations/hubspot/callback")
async def hubspot_callback(request: Request, user: dict = Depends(require_auth)):
    """Handle HubSpot OAuth callback."""
    return _deprecated_response("hubspot")


@router.post("/integrations/hubspot/disconnect")
async def hubspot_disconnect(request: Request, user: dict = Depends(require_auth)):
    """Disconnect HubSpot integration."""
    await delete_integration(user["id"], "hubspot")
    return RedirectResponse(url="/integrations", status_code=303)


@router.get("/integrations/hubspot/companies")
async def hubspot_companies(request: Request, user: dict = Depends(require_onboarding)):
    """Fetch companies from HubSpot for import selection."""
    return _deprecated_response("hubspot")


@router.post("/integrations/hubspot/import")
async def hubspot_import(request: Request, user: dict = Depends(require_onboarding)):
    """Import selected HubSpot companies into an Auggie list."""
    return _deprecated_response("hubspot")


# ==========================================================================
# Instantly
# ==========================================================================

@router.post("/integrations/instantly/connect")
async def instantly_connect(request: Request, user: dict = Depends(require_auth)):
    """Save Instantly API key after validation."""
    return _deprecated_response("instantly")


@router.post("/integrations/instantly/disconnect")
async def instantly_disconnect(request: Request, user: dict = Depends(require_auth)):
    """Disconnect Instantly integration."""
    await delete_integration(user["id"], "instantly")
    return RedirectResponse(url="/integrations", status_code=303)


@router.get("/integrations/instantly/campaigns")
async def instantly_campaigns(request: Request, user: dict = Depends(require_onboarding)):
    """List Instantly campaigns."""
    return _deprecated_response("instantly")


# ==========================================================================
# Smartlead
# ==========================================================================

@router.post("/integrations/smartlead/connect")
async def smartlead_connect(request: Request, user: dict = Depends(require_auth)):
    """Save Smartlead API key after validation."""
    return _deprecated_response("smartlead")


@router.post("/integrations/smartlead/disconnect")
async def smartlead_disconnect(request: Request, user: dict = Depends(require_auth)):
    """Disconnect Smartlead integration."""
    await delete_integration(user["id"], "smartlead")
    return RedirectResponse(url="/integrations", status_code=303)


@router.get("/integrations/smartlead/campaigns")
async def smartlead_campaigns(request: Request, user: dict = Depends(require_onboarding)):
    """List Smartlead campaigns."""
    return _deprecated_response("smartlead")


# ==========================================================================
# Salesforce
# ==========================================================================

@router.get("/integrations/salesforce/connect")
async def salesforce_connect(request: Request, user: dict = Depends(require_auth)):
    """Redirect to Salesforce OAuth."""
    return _deprecated_response("salesforce")


@router.get("/integrations/salesforce/callback")
async def salesforce_callback(request: Request, user: dict = Depends(require_auth)):
    """Handle Salesforce OAuth callback."""
    return _deprecated_response("salesforce")


@router.post("/integrations/salesforce/disconnect")
async def salesforce_disconnect(request: Request, user: dict = Depends(require_auth)):
    """Disconnect Salesforce integration."""
    await delete_integration(user["id"], "salesforce")
    return RedirectResponse(url="/integrations", status_code=303)


@router.get("/integrations/salesforce/accounts")
async def salesforce_accounts(request: Request, user: dict = Depends(require_onboarding)):
    """Fetch accounts from Salesforce for import selection."""
    return _deprecated_response("salesforce")


@router.post("/integrations/salesforce/import")
async def salesforce_import(request: Request, user: dict = Depends(require_onboarding)):
    """Import selected Salesforce accounts into an Auggie list."""
    return _deprecated_response("salesforce")


# ==========================================================================
# Outreach
# ==========================================================================

@router.get("/integrations/outreach/connect")
async def outreach_connect(request: Request, user: dict = Depends(require_auth)):
    """Redirect to Outreach OAuth."""
    return _deprecated_response("outreach")


@router.get("/integrations/outreach/callback")
async def outreach_callback(request: Request, user: dict = Depends(require_auth)):
    """Handle Outreach OAuth callback."""
    return _deprecated_response("outreach")


@router.post("/integrations/outreach/disconnect")
async def outreach_disconnect(request: Request, user: dict = Depends(require_auth)):
    """Disconnect Outreach integration."""
    await delete_integration(user["id"], "outreach")
    return RedirectResponse(url="/integrations", status_code=303)


@router.get("/integrations/outreach/sequences")
async def outreach_sequences(request: Request, user: dict = Depends(require_onboarding)):
    """List Outreach sequences."""
    return _deprecated_response("outreach")


# ==========================================================================
# SalesLoft
# ==========================================================================

@router.get("/integrations/salesloft/connect")
async def salesloft_connect(request: Request, user: dict = Depends(require_auth)):
    """Redirect to SalesLoft OAuth."""
    return _deprecated_response("salesloft")


@router.get("/integrations/salesloft/callback")
async def salesloft_callback(request: Request, user: dict = Depends(require_auth)):
    """Handle SalesLoft OAuth callback."""
    return _deprecated_response("salesloft")


@router.post("/integrations/salesloft/disconnect")
async def salesloft_disconnect(request: Request, user: dict = Depends(require_auth)):
    """Disconnect SalesLoft integration."""
    await delete_integration(user["id"], "salesloft")
    return RedirectResponse(url="/integrations", status_code=303)


@router.get("/integrations/salesloft/cadences")
async def salesloft_cadences(request: Request, user: dict = Depends(require_onboarding)):
    """List SalesLoft cadences."""
    return _deprecated_response("salesloft")


# ==========================================================================
# Gong Engage
# ==========================================================================

@router.get("/integrations/gong_engage/connect")
async def gong_engage_connect(request: Request, user: dict = Depends(require_auth)):
    """Redirect to Gong Engage OAuth."""
    return _deprecated_response("gong_engage")


@router.get("/integrations/gong_engage/callback")
async def gong_engage_callback(request: Request, user: dict = Depends(require_auth)):
    """Handle Gong Engage OAuth callback."""
    return _deprecated_response("gong_engage")


@router.post("/integrations/gong_engage/disconnect")
async def gong_engage_disconnect(request: Request, user: dict = Depends(require_auth)):
    """Disconnect Gong Engage integration."""
    await delete_integration(user["id"], "gong_engage")
    return RedirectResponse(url="/integrations", status_code=303)


@router.get("/integrations/gong_engage/flows")
async def gong_engage_flows(request: Request, user: dict = Depends(require_onboarding)):
    """List Gong Engage flows."""
    return _deprecated_response("gong_engage")


# ==========================================================================
# ZoomInfo
# ==========================================================================

@router.get("/integrations/zoominfo/connect")
async def zoominfo_connect(request: Request, user: dict = Depends(require_auth)):
    """Redirect to ZoomInfo OAuth with PKCE."""
    return _deprecated_response("zoominfo")


@router.get("/integrations/zoominfo/callback")
async def zoominfo_callback(request: Request, user: dict = Depends(require_auth)):
    """Handle ZoomInfo OAuth callback with PKCE verifier."""
    return _deprecated_response("zoominfo")


@router.post("/integrations/zoominfo/disconnect")
async def zoominfo_disconnect(request: Request, user: dict = Depends(require_auth)):
    """Disconnect ZoomInfo integration."""
    await delete_integration(user["id"], "zoominfo")
    return RedirectResponse(url="/integrations", status_code=303)


@router.get("/integrations/zoominfo/companies")
async def zoominfo_companies(request: Request, user: dict = Depends(require_onboarding)):
    """Search companies via ZoomInfo API."""
    return _deprecated_response("zoominfo")


@router.post("/integrations/zoominfo/import")
async def zoominfo_import(request: Request, user: dict = Depends(require_onboarding)):
    """Import selected ZoomInfo companies into an Auggie list."""
    return _deprecated_response("zoominfo")


# ==========================================================================
# Apollo
# ==========================================================================

@router.post("/integrations/apollo/connect")
async def apollo_connect(request: Request, user: dict = Depends(require_auth)):
    """Save Apollo API key after validation."""
    body = ApiKeyConnectRequest(**(await request.json()))
    return await _apikey_connect(user, "apollo", body.api_key, apollo_validate, "Apollo API key")


@router.post("/integrations/apollo/disconnect")
async def apollo_disconnect(request: Request, user: dict = Depends(require_auth)):
    """Disconnect Apollo integration."""
    await delete_integration(user["id"], "apollo")
    return RedirectResponse(url="/integrations", status_code=303)


@router.get("/integrations/apollo/lists")
async def apollo_lists(request: Request, user: dict = Depends(require_onboarding)):
    """List saved Apollo lists."""
    from services.apollo import list_saved_lists
    try:
        lists = await list_saved_lists(user["id"])
    except Exception as e:
        logger.error("Apollo API error: %s", e, extra={"event_type": "integration_provider_error", "provider": "apollo", "status_code": 502})
        raise HTTPException(status_code=502, detail=f"Apollo API error: {e}")
    return JSONResponse(lists)


@router.post("/integrations/apollo/import")
async def apollo_import(request: Request, user: dict = Depends(require_onboarding)):
    """Import companies from an Apollo saved list into an Auggie list."""
    from services.apollo import fetch_list_companies

    body = ApolloImportRequest(**(await request.json()))
    data = await fetch_list_companies(user["id"], body.list_id)
    logger.info("Apollo import response keys: %s", list(data.keys()) if isinstance(data, dict) else type(data))
    organizations = data.get("organizations", []) or data.get("accounts", [])
    logger.info("Apollo import found %d organizations", len(organizations))
    if organizations:
        logger.info("Apollo first org keys: %s", list(organizations[0].keys()))

    def extractor(org):
        domain = (org.get("primary_domain") or org.get("website_url") or "").strip()
        return domain, org.get("id")  # Apollo org ID

    def source_metadata(id_map):
        return {"provider": "apollo", "org_ids": id_map}

    return await _run_crm_import(user, organizations, body.name, extractor, source_metadata_fn=source_metadata)


# ==========================================================================
# PDL (People Data Labs)
# ==========================================================================

@router.post("/integrations/pdl/connect")
async def pdl_connect(request: Request, user: dict = Depends(require_auth)):
    """Save PDL API key after validation."""
    return _deprecated_response("pdl")


@router.post("/integrations/pdl/disconnect")
async def pdl_disconnect(request: Request, user: dict = Depends(require_auth)):
    """Disconnect PDL integration."""
    await delete_integration(user["id"], "pdl")
    return RedirectResponse(url="/integrations", status_code=303)


@router.post("/integrations/pdl/search")
async def pdl_search(request: Request, user: dict = Depends(require_onboarding)):
    """Search companies via PDL API and return results for UI preview."""
    return _deprecated_response("pdl")


@router.post("/integrations/pdl/import")
async def pdl_import(request: Request, user: dict = Depends(require_onboarding)):
    """Search PDL and import matching companies into an Auggie list."""
    return _deprecated_response("pdl")


# ==========================================================================
# Lusha
# ==========================================================================

@router.post("/integrations/lusha/connect")
async def lusha_connect(request: Request, user: dict = Depends(require_auth)):
    """Save Lusha API key after validation."""
    return _deprecated_response("lusha")


@router.post("/integrations/lusha/disconnect")
async def lusha_disconnect(request: Request, user: dict = Depends(require_auth)):
    """Disconnect Lusha integration."""
    await delete_integration(user["id"], "lusha")
    return RedirectResponse(url="/integrations", status_code=303)


@router.post("/integrations/lusha/import")
async def lusha_import(request: Request, user: dict = Depends(require_onboarding)):
    """Search Lusha with filters and import matching companies into an Auggie list."""
    return _deprecated_response("lusha")


# ==========================================================================
# Cognism
# ==========================================================================

@router.post("/integrations/cognism/connect")
async def cognism_connect(request: Request, user: dict = Depends(require_auth)):
    """Save Cognism API key after validation."""
    return _deprecated_response("cognism")


@router.post("/integrations/cognism/disconnect")
async def cognism_disconnect(request: Request, user: dict = Depends(require_auth)):
    """Disconnect Cognism integration."""
    await delete_integration(user["id"], "cognism")
    return RedirectResponse(url="/integrations", status_code=303)


@router.post("/integrations/cognism/import")
async def cognism_import(request: Request, user: dict = Depends(require_onboarding)):
    """Search Cognism with filters and import matching companies into an Auggie list."""
    return _deprecated_response("cognism")


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
