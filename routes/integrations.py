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
    normalize_url, templates, logger,
    _oauth_connect, _oauth_callback, _apikey_connect, _run_crm_import,
)
from routes.schemas import (
    ApiKeyConnectRequest, HubSpotImportRequest, SalesforceImportRequest,
    ApolloImportRequest, OceanImportRequest, SlackConnectRequest,
)
from services.hubspot import get_authorize_url as hubspot_authorize_url, exchange_code as hubspot_exchange_code
from services.salesforce import get_authorize_url as salesforce_authorize_url, exchange_code as salesforce_exchange_code
from services.outreach import get_authorize_url as outreach_authorize_url, exchange_code as outreach_exchange_code
from services.salesloft import get_authorize_url as salesloft_authorize_url, exchange_code as salesloft_exchange_code
from services.instantly import validate_api_key as instantly_validate
from services.smartlead import validate_api_key as smartlead_validate
from services.apollo import validate_integration_api_key as apollo_validate
from services.ocean import validate_api_key as ocean_validate
from services.notifications import validate_webhook_url, send_slack_notification

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
        "integrations.html",
        {
            "request": request,
            "user": user,
            "integrations": integration_map,
            "credits": usage.get("bonus_credits", 0) / 100,
            "is_admin": usage.get("is_admin", False),
        }
    )


# ==========================================================================
# HubSpot
# ==========================================================================

@router.get("/integrations/hubspot/connect")
async def hubspot_connect(request: Request, user: dict = Depends(require_auth)):
    """Redirect to HubSpot OAuth."""
    return await _oauth_connect(request, "hubspot", hubspot_authorize_url)


@router.get("/integrations/hubspot/callback")
async def hubspot_callback(request: Request, user: dict = Depends(require_auth)):
    """Handle HubSpot OAuth callback."""
    return await _oauth_callback(
        request, user, "hubspot", hubspot_exchange_code,
        expires_in_default=21600,
        metadata_fn=lambda td: {"hub_id": td.get("hub_id")},
    )


@router.post("/integrations/hubspot/disconnect")
async def hubspot_disconnect(request: Request, user: dict = Depends(require_auth)):
    """Disconnect HubSpot integration."""
    await delete_integration(user["id"], "hubspot")
    return RedirectResponse(url="/integrations", status_code=303)


@router.get("/integrations/hubspot/companies")
async def hubspot_companies(request: Request, user: dict = Depends(require_onboarding)):
    """Fetch companies from HubSpot for import selection."""
    from services.hubspot import fetch_companies
    after = request.query_params.get("after")
    try:
        data = await fetch_companies(user["id"], limit=100, after=after)
    except Exception as e:
        logger.error("HubSpot API error: %s", e)
        raise HTTPException(status_code=502, detail="HubSpot API error")
    return JSONResponse(data)


@router.post("/integrations/hubspot/import")
async def hubspot_import(request: Request, user: dict = Depends(require_onboarding)):
    """Import selected HubSpot companies into an Auggie list."""
    body = HubSpotImportRequest(**(await request.json()))

    def extractor(c):
        domain = c.get("domain", "").strip()
        hid = str(c.get("id", ""))
        return domain, hid

    return await _run_crm_import(
        user, body.companies, body.name, extractor,
        source_metadata_fn=lambda m: {"provider": "hubspot", "hubspot_company_map": m},
    )


# ==========================================================================
# Instantly
# ==========================================================================

@router.post("/integrations/instantly/connect")
async def instantly_connect(request: Request, user: dict = Depends(require_auth)):
    """Save Instantly API key after validation."""
    body = ApiKeyConnectRequest(**(await request.json()))
    return await _apikey_connect(user, "instantly", body.api_key, instantly_validate, "Instantly API key")


@router.post("/integrations/instantly/disconnect")
async def instantly_disconnect(request: Request, user: dict = Depends(require_auth)):
    """Disconnect Instantly integration."""
    await delete_integration(user["id"], "instantly")
    return RedirectResponse(url="/integrations", status_code=303)


@router.get("/integrations/instantly/campaigns")
async def instantly_campaigns(request: Request, user: dict = Depends(require_onboarding)):
    """List Instantly campaigns."""
    from services.instantly import list_campaigns
    try:
        campaigns = await list_campaigns(user["id"])
    except Exception as e:
        logger.error("Instantly API error: %s", e)
        raise HTTPException(status_code=502, detail="Instantly API error")
    return JSONResponse(campaigns)


# ==========================================================================
# Smartlead
# ==========================================================================

@router.post("/integrations/smartlead/connect")
async def smartlead_connect(request: Request, user: dict = Depends(require_auth)):
    """Save Smartlead API key after validation."""
    body = ApiKeyConnectRequest(**(await request.json()))
    return await _apikey_connect(user, "smartlead", body.api_key, smartlead_validate, "Smartlead API key")


@router.post("/integrations/smartlead/disconnect")
async def smartlead_disconnect(request: Request, user: dict = Depends(require_auth)):
    """Disconnect Smartlead integration."""
    await delete_integration(user["id"], "smartlead")
    return RedirectResponse(url="/integrations", status_code=303)


@router.get("/integrations/smartlead/campaigns")
async def smartlead_campaigns(request: Request, user: dict = Depends(require_onboarding)):
    """List Smartlead campaigns."""
    from services.smartlead import list_campaigns
    try:
        campaigns = await list_campaigns(user["id"])
    except Exception as e:
        logger.error("Smartlead API error: %s", e)
        raise HTTPException(status_code=502, detail="Smartlead API error")
    return JSONResponse(campaigns)


# ==========================================================================
# Salesforce
# ==========================================================================

@router.get("/integrations/salesforce/connect")
async def salesforce_connect(request: Request, user: dict = Depends(require_auth)):
    """Redirect to Salesforce OAuth."""
    return await _oauth_connect(request, "salesforce", salesforce_authorize_url)


@router.get("/integrations/salesforce/callback")
async def salesforce_callback(request: Request, user: dict = Depends(require_auth)):
    """Handle Salesforce OAuth callback."""
    return await _oauth_callback(
        request, user, "salesforce", salesforce_exchange_code,
        expires_in_default=7200,
        metadata_fn=lambda td: {
            "instance_url": td.get("instance_url", ""),
            "id": td.get("id", ""),
        },
    )


@router.post("/integrations/salesforce/disconnect")
async def salesforce_disconnect(request: Request, user: dict = Depends(require_auth)):
    """Disconnect Salesforce integration."""
    await delete_integration(user["id"], "salesforce")
    return RedirectResponse(url="/integrations", status_code=303)


@router.get("/integrations/salesforce/accounts")
async def salesforce_accounts(request: Request, user: dict = Depends(require_onboarding)):
    """Fetch accounts from Salesforce for import selection."""
    from services.salesforce import fetch_accounts
    offset = int(request.query_params.get("offset", "0"))
    try:
        data = await fetch_accounts(user["id"], limit=100, offset=offset)
    except Exception as e:
        logger.error("Salesforce API error: %s", e)
        raise HTTPException(status_code=502, detail="Salesforce API error")
    return JSONResponse(data)


@router.post("/integrations/salesforce/import")
async def salesforce_import(request: Request, user: dict = Depends(require_onboarding)):
    """Import selected Salesforce accounts into an Auggie list."""
    body = SalesforceImportRequest(**(await request.json()))

    def extractor(a):
        website = a.get("website", "").strip()
        sf_id = str(a.get("id", ""))
        return website, sf_id

    return await _run_crm_import(
        user, body.accounts, body.name, extractor,
        source_metadata_fn=lambda m: {"provider": "salesforce", "salesforce_account_map": m},
    )


# ==========================================================================
# Outreach
# ==========================================================================

@router.get("/integrations/outreach/connect")
async def outreach_connect(request: Request, user: dict = Depends(require_auth)):
    """Redirect to Outreach OAuth."""
    return await _oauth_connect(request, "outreach", outreach_authorize_url)


@router.get("/integrations/outreach/callback")
async def outreach_callback(request: Request, user: dict = Depends(require_auth)):
    """Handle Outreach OAuth callback."""
    return await _oauth_callback(request, user, "outreach", outreach_exchange_code)


@router.post("/integrations/outreach/disconnect")
async def outreach_disconnect(request: Request, user: dict = Depends(require_auth)):
    """Disconnect Outreach integration."""
    await delete_integration(user["id"], "outreach")
    return RedirectResponse(url="/integrations", status_code=303)


@router.get("/integrations/outreach/sequences")
async def outreach_sequences(request: Request, user: dict = Depends(require_onboarding)):
    """List Outreach sequences."""
    from services.outreach import list_sequences
    try:
        sequences = await list_sequences(user["id"])
    except Exception as e:
        logger.error("Outreach API error: %s", e)
        raise HTTPException(status_code=502, detail="Outreach API error")
    return JSONResponse(sequences)


# ==========================================================================
# SalesLoft
# ==========================================================================

@router.get("/integrations/salesloft/connect")
async def salesloft_connect(request: Request, user: dict = Depends(require_auth)):
    """Redirect to SalesLoft OAuth."""
    return await _oauth_connect(request, "salesloft", salesloft_authorize_url)


@router.get("/integrations/salesloft/callback")
async def salesloft_callback(request: Request, user: dict = Depends(require_auth)):
    """Handle SalesLoft OAuth callback."""
    return await _oauth_callback(request, user, "salesloft", salesloft_exchange_code)


@router.post("/integrations/salesloft/disconnect")
async def salesloft_disconnect(request: Request, user: dict = Depends(require_auth)):
    """Disconnect SalesLoft integration."""
    await delete_integration(user["id"], "salesloft")
    return RedirectResponse(url="/integrations", status_code=303)


@router.get("/integrations/salesloft/cadences")
async def salesloft_cadences(request: Request, user: dict = Depends(require_onboarding)):
    """List SalesLoft cadences."""
    from services.salesloft import list_cadences
    try:
        cadences = await list_cadences(user["id"])
    except Exception as e:
        logger.error("SalesLoft API error: %s", e)
        raise HTTPException(status_code=502, detail="SalesLoft API error")
    return JSONResponse(cadences)


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
        logger.error("Apollo API error: %s", e)
        raise HTTPException(status_code=502, detail="Apollo API error")
    return JSONResponse(lists)


@router.post("/integrations/apollo/import")
async def apollo_import(request: Request, user: dict = Depends(require_onboarding)):
    """Import companies from an Apollo saved list into an Auggie list."""
    from services.apollo import fetch_list_companies

    body = ApolloImportRequest(**(await request.json()))
    data = await fetch_list_companies(user["id"], body.list_id)
    organizations = data.get("organizations", [])

    def extractor(org):
        domain = (org.get("primary_domain") or org.get("website_url") or "").strip()
        return domain, None

    return await _run_crm_import(user, organizations, body.name, extractor)


# ==========================================================================
# Ocean.io
# ==========================================================================

@router.post("/integrations/ocean/connect")
async def ocean_connect(request: Request, user: dict = Depends(require_auth)):
    """Save Ocean.io API key after validation."""
    body = ApiKeyConnectRequest(**(await request.json()))
    return await _apikey_connect(user, "ocean", body.api_key, ocean_validate, "Ocean.io API key")


@router.post("/integrations/ocean/disconnect")
async def ocean_disconnect(request: Request, user: dict = Depends(require_auth)):
    """Disconnect Ocean.io integration."""
    await delete_integration(user["id"], "ocean")
    return RedirectResponse(url="/integrations", status_code=303)


@router.get("/integrations/ocean/audiences")
async def ocean_audiences(request: Request, user: dict = Depends(require_onboarding)):
    """List Ocean.io audiences."""
    from services.ocean import list_audiences
    try:
        audiences = await list_audiences(user["id"])
    except Exception as e:
        logger.error("Ocean.io API error: %s", e)
        raise HTTPException(status_code=502, detail="Ocean.io API error")
    return JSONResponse(audiences)


@router.post("/integrations/ocean/import")
async def ocean_import(request: Request, user: dict = Depends(require_onboarding)):
    """Import companies from an Ocean.io audience into an Auggie list."""
    from services.ocean import fetch_audience_companies

    body = OceanImportRequest(**(await request.json()))
    data = await fetch_audience_companies(user["id"], body.audience_id)
    companies = data.get("companies", data.get("data", []))

    def extractor(company):
        domain = (company.get("domain") or company.get("website") or "").strip()
        return domain, None

    return await _run_crm_import(user, companies, body.name, extractor)


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
# Clay integration landing page
# ==========================================================================

@router.get("/integrations/clay", response_class=HTMLResponse)
async def integrations_clay(request: Request):
    """Clay integration landing page for marketplace listing."""
    from auth import get_current_user
    user = await get_current_user(request)
    return templates.TemplateResponse(
        "integrations_clay.html",
        {"request": request, "user": user}
    )
