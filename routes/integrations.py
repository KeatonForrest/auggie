"""Integration routes: OAuth + API-key connect/disconnect/callback/import for all providers."""

import logging

from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse

from auth import require_auth, require_onboarding
from config import get_settings
from database import (
    get_user_usage, use_credit, get_enriched_contacts,
    create_list, add_list_accounts, update_list_credits,
    get_list, get_list_accounts,
)
from api.validation import validate_company_url
from api.tasks import create_tracked_task
from routes._helpers import normalize_url, templates, logger

settings = get_settings()
router = APIRouter()


# ==========================================================================
# Integrations page
# ==========================================================================

@router.get("/integrations", response_class=HTMLResponse)
async def integrations_page(request: Request, user: dict = Depends(require_onboarding)):
    """Integration management page."""
    from database import get_user_integrations
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
    import secrets
    from services.hubspot import get_authorize_url
    state = secrets.token_urlsafe(24)
    request.session["_hubspot_state_"] = state
    url = get_authorize_url(state)
    return RedirectResponse(url=url)


@router.get("/integrations/hubspot/callback")
async def hubspot_callback(request: Request, user: dict = Depends(require_auth)):
    """Handle HubSpot OAuth callback."""
    from datetime import datetime as dt, timezone, timedelta
    from services.hubspot import exchange_code
    from database import upsert_integration

    code = request.query_params.get("code")
    state = request.query_params.get("state")

    if not code or state != request.session.get("_hubspot_state_"):
        raise HTTPException(status_code=400, detail="Invalid OAuth callback")

    request.session.pop("_hubspot_state_", None)

    token_data = await exchange_code(code)
    expires_at = dt.now(timezone.utc) + timedelta(seconds=token_data.get("expires_in", 21600))

    await upsert_integration(
        user_id=user["id"],
        provider="hubspot",
        access_token=token_data["access_token"],
        refresh_token=token_data.get("refresh_token"),
        token_expires_at=expires_at,
        metadata={"hub_id": token_data.get("hub_id")},
    )

    return RedirectResponse(url="/integrations", status_code=302)


@router.post("/integrations/hubspot/disconnect")
async def hubspot_disconnect(request: Request, user: dict = Depends(require_auth)):
    """Disconnect HubSpot integration."""
    from database import delete_integration
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
    from api.jobs import run_list_analysis
    from database import upsert_integration, set_list_source

    body = await request.json()
    companies = body.get("companies", [])
    list_name = body.get("name", "HubSpot Import")

    if not companies:
        raise HTTPException(status_code=400, detail="No companies selected")

    # Build URLs and HubSpot ID map
    valid_urls = []
    hubspot_map = {}
    seen = set()
    for c in companies:
        domain = c.get("domain", "").strip()
        hubspot_id = str(c.get("id", ""))
        if not domain or domain in seen:
            continue
        url = normalize_url(domain)
        try:
            url = validate_company_url(url)
        except ValueError:
            continue
        seen.add(domain)
        valid_urls.append(url)
        hubspot_map[url] = hubspot_id
        if len(valid_urls) >= 100:
            break

    if not valid_urls:
        raise HTTPException(status_code=400, detail="No valid domains found in selected companies")

    # Check credits
    usage = await get_user_usage(user["id"])
    is_admin = usage.get("is_admin", False)
    needed = len(valid_urls) * 100
    if not is_admin and usage.get("bonus_credits", 0) < needed:
        raise HTTPException(
            status_code=402,
            detail=f"Not enough credits. Need {len(valid_urls)}, have {usage.get('bonus_credits', 0) // 100}."
        )

    if not is_admin:
        await use_credit(user["id"], cents=needed)

    lst = await create_list(user["id"], api_key_id=None, name=list_name)
    await add_list_accounts(lst["id"], valid_urls)
    await update_list_credits(lst["id"], needed)
    await set_list_source(lst["id"], {
        "provider": "hubspot",
        "hubspot_company_map": hubspot_map,
    })

    create_tracked_task(
        run_list_analysis(lst["id"], user["id"], api_key_id=None, is_admin=is_admin),
        name=f"list-{lst['id']}",
    )

    return JSONResponse({"success": True, "list_id": lst["id"]})


# ==========================================================================
# Instantly
# ==========================================================================

@router.post("/integrations/instantly/connect")
async def instantly_connect(request: Request, user: dict = Depends(require_auth)):
    """Save Instantly API key after validation."""
    from services.instantly import validate_api_key
    from database import upsert_integration

    body = await request.json()
    api_key = body.get("api_key", "").strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="API key is required")

    valid = await validate_api_key(api_key)
    if not valid:
        raise HTTPException(status_code=400, detail="Invalid Instantly API key")

    await upsert_integration(
        user_id=user["id"],
        provider="instantly",
        access_token=api_key,
    )

    return JSONResponse({"success": True})


@router.post("/integrations/instantly/disconnect")
async def instantly_disconnect(request: Request, user: dict = Depends(require_auth)):
    """Disconnect Instantly integration."""
    from database import delete_integration
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
    from services.smartlead import validate_api_key
    from database import upsert_integration

    body = await request.json()
    api_key = body.get("api_key", "").strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="API key is required")

    valid = await validate_api_key(api_key)
    if not valid:
        raise HTTPException(status_code=400, detail="Invalid Smartlead API key")

    await upsert_integration(
        user_id=user["id"],
        provider="smartlead",
        access_token=api_key,
    )

    return JSONResponse({"success": True})


@router.post("/integrations/smartlead/disconnect")
async def smartlead_disconnect(request: Request, user: dict = Depends(require_auth)):
    """Disconnect Smartlead integration."""
    from database import delete_integration
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
    import secrets
    from services.salesforce import get_authorize_url
    state = secrets.token_urlsafe(24)
    request.session["_salesforce_state_"] = state
    url = get_authorize_url(state)
    return RedirectResponse(url=url)


@router.get("/integrations/salesforce/callback")
async def salesforce_callback(request: Request, user: dict = Depends(require_auth)):
    """Handle Salesforce OAuth callback."""
    from datetime import datetime as dt, timezone, timedelta
    from services.salesforce import exchange_code
    from database import upsert_integration

    code = request.query_params.get("code")
    state = request.query_params.get("state")

    if not code or state != request.session.get("_salesforce_state_"):
        raise HTTPException(status_code=400, detail="Invalid OAuth callback")

    request.session.pop("_salesforce_state_", None)

    token_data = await exchange_code(code)
    expires_at = dt.now(timezone.utc) + timedelta(seconds=7200)

    await upsert_integration(
        user_id=user["id"],
        provider="salesforce",
        access_token=token_data["access_token"],
        refresh_token=token_data.get("refresh_token"),
        token_expires_at=expires_at,
        metadata={
            "instance_url": token_data.get("instance_url", ""),
            "id": token_data.get("id", ""),
        },
    )

    return RedirectResponse(url="/integrations", status_code=302)


@router.post("/integrations/salesforce/disconnect")
async def salesforce_disconnect(request: Request, user: dict = Depends(require_auth)):
    """Disconnect Salesforce integration."""
    from database import delete_integration
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
    from api.jobs import run_list_analysis
    from database import set_list_source

    body = await request.json()
    accounts = body.get("accounts", [])
    list_name = body.get("name", "Salesforce Import")

    if not accounts:
        raise HTTPException(status_code=400, detail="No accounts selected")

    valid_urls = []
    sf_map = {}
    seen = set()
    for a in accounts:
        website = a.get("website", "").strip()
        sf_id = str(a.get("id", ""))
        if not website or website in seen:
            continue
        url = normalize_url(website)
        try:
            url = validate_company_url(url)
        except ValueError:
            continue
        seen.add(website)
        valid_urls.append(url)
        sf_map[url] = sf_id
        if len(valid_urls) >= 100:
            break

    if not valid_urls:
        raise HTTPException(status_code=400, detail="No valid domains found in selected accounts")

    usage = await get_user_usage(user["id"])
    is_admin = usage.get("is_admin", False)
    needed = len(valid_urls) * 100
    if not is_admin and usage.get("bonus_credits", 0) < needed:
        raise HTTPException(
            status_code=402,
            detail=f"Not enough credits. Need {len(valid_urls)}, have {usage.get('bonus_credits', 0) // 100}."
        )

    if not is_admin:
        await use_credit(user["id"], cents=needed)

    lst = await create_list(user["id"], api_key_id=None, name=list_name)
    await add_list_accounts(lst["id"], valid_urls)
    await update_list_credits(lst["id"], needed)
    await set_list_source(lst["id"], {
        "provider": "salesforce",
        "salesforce_account_map": sf_map,
    })

    create_tracked_task(
        run_list_analysis(lst["id"], user["id"], api_key_id=None, is_admin=is_admin),
        name=f"list-{lst['id']}",
    )

    return JSONResponse({"success": True, "list_id": lst["id"]})


# ==========================================================================
# Outreach
# ==========================================================================

@router.get("/integrations/outreach/connect")
async def outreach_connect(request: Request, user: dict = Depends(require_auth)):
    """Redirect to Outreach OAuth."""
    import secrets
    from services.outreach import get_authorize_url
    state = secrets.token_urlsafe(24)
    request.session["_outreach_state_"] = state
    url = get_authorize_url(state)
    return RedirectResponse(url=url)


@router.get("/integrations/outreach/callback")
async def outreach_callback(request: Request, user: dict = Depends(require_auth)):
    """Handle Outreach OAuth callback."""
    from datetime import datetime as dt, timezone, timedelta
    from services.outreach import exchange_code
    from database import upsert_integration

    code = request.query_params.get("code")
    state = request.query_params.get("state")

    if not code or state != request.session.get("_outreach_state_"):
        raise HTTPException(status_code=400, detail="Invalid OAuth callback")

    request.session.pop("_outreach_state_", None)

    token_data = await exchange_code(code)
    expires_at = dt.now(timezone.utc) + timedelta(seconds=token_data.get("expires_in", 7200))

    await upsert_integration(
        user_id=user["id"],
        provider="outreach",
        access_token=token_data["access_token"],
        refresh_token=token_data.get("refresh_token"),
        token_expires_at=expires_at,
    )

    return RedirectResponse(url="/integrations", status_code=302)


@router.post("/integrations/outreach/disconnect")
async def outreach_disconnect(request: Request, user: dict = Depends(require_auth)):
    """Disconnect Outreach integration."""
    from database import delete_integration
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
    import secrets
    from services.salesloft import get_authorize_url
    state = secrets.token_urlsafe(24)
    request.session["_salesloft_state_"] = state
    url = get_authorize_url(state)
    return RedirectResponse(url=url)


@router.get("/integrations/salesloft/callback")
async def salesloft_callback(request: Request, user: dict = Depends(require_auth)):
    """Handle SalesLoft OAuth callback."""
    from datetime import datetime as dt, timezone, timedelta
    from services.salesloft import exchange_code
    from database import upsert_integration

    code = request.query_params.get("code")
    state = request.query_params.get("state")

    if not code or state != request.session.get("_salesloft_state_"):
        raise HTTPException(status_code=400, detail="Invalid OAuth callback")

    request.session.pop("_salesloft_state_", None)

    token_data = await exchange_code(code)
    expires_at = dt.now(timezone.utc) + timedelta(seconds=token_data.get("expires_in", 7200))

    await upsert_integration(
        user_id=user["id"],
        provider="salesloft",
        access_token=token_data["access_token"],
        refresh_token=token_data.get("refresh_token"),
        token_expires_at=expires_at,
    )

    return RedirectResponse(url="/integrations", status_code=302)


@router.post("/integrations/salesloft/disconnect")
async def salesloft_disconnect(request: Request, user: dict = Depends(require_auth)):
    """Disconnect SalesLoft integration."""
    from database import delete_integration
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
    from services.apollo import validate_integration_api_key
    from database import upsert_integration

    body = await request.json()
    api_key = body.get("api_key", "").strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="API key is required")

    valid = await validate_integration_api_key(api_key)
    if not valid:
        raise HTTPException(status_code=400, detail="Invalid Apollo API key")

    await upsert_integration(
        user_id=user["id"],
        provider="apollo",
        access_token=api_key,
    )

    return JSONResponse({"success": True})


@router.post("/integrations/apollo/disconnect")
async def apollo_disconnect(request: Request, user: dict = Depends(require_auth)):
    """Disconnect Apollo integration."""
    from database import delete_integration
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
    from api.jobs import run_list_analysis

    body = await request.json()
    apollo_list_id = body.get("list_id", "")
    list_name = body.get("name", "Apollo Import")

    if not apollo_list_id:
        raise HTTPException(status_code=400, detail="list_id is required")

    data = await fetch_list_companies(user["id"], apollo_list_id)
    organizations = data.get("organizations", [])

    valid_urls = []
    seen = set()
    for org in organizations:
        domain = (org.get("primary_domain") or org.get("website_url") or "").strip()
        if not domain or domain in seen:
            continue
        url = normalize_url(domain)
        try:
            url = validate_company_url(url)
        except ValueError:
            continue
        seen.add(domain)
        valid_urls.append(url)
        if len(valid_urls) >= 100:
            break

    if not valid_urls:
        raise HTTPException(status_code=400, detail="No valid domains found in Apollo list")

    usage = await get_user_usage(user["id"])
    is_admin = usage.get("is_admin", False)
    needed = len(valid_urls) * 100
    if not is_admin and usage.get("bonus_credits", 0) < needed:
        raise HTTPException(
            status_code=402,
            detail=f"Not enough credits. Need {len(valid_urls)}, have {usage.get('bonus_credits', 0) // 100}."
        )

    if not is_admin:
        await use_credit(user["id"], cents=needed)

    lst = await create_list(user["id"], api_key_id=None, name=list_name)
    await add_list_accounts(lst["id"], valid_urls)
    await update_list_credits(lst["id"], needed)

    create_tracked_task(
        run_list_analysis(lst["id"], user["id"], api_key_id=None, is_admin=is_admin),
        name=f"list-{lst['id']}",
    )

    return JSONResponse({"success": True, "list_id": lst["id"]})


# ==========================================================================
# Ocean.io
# ==========================================================================

@router.post("/integrations/ocean/connect")
async def ocean_connect(request: Request, user: dict = Depends(require_auth)):
    """Save Ocean.io API key after validation."""
    from services.ocean import validate_api_key
    from database import upsert_integration

    body = await request.json()
    api_key = body.get("api_key", "").strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="API key is required")

    valid = await validate_api_key(api_key)
    if not valid:
        raise HTTPException(status_code=400, detail="Invalid Ocean.io API key")

    await upsert_integration(
        user_id=user["id"],
        provider="ocean",
        access_token=api_key,
    )

    return JSONResponse({"success": True})


@router.post("/integrations/ocean/disconnect")
async def ocean_disconnect(request: Request, user: dict = Depends(require_auth)):
    """Disconnect Ocean.io integration."""
    from database import delete_integration
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
    from api.jobs import run_list_analysis

    body = await request.json()
    audience_id = body.get("audience_id", "")
    list_name = body.get("name", "Ocean.io Import")

    if not audience_id:
        raise HTTPException(status_code=400, detail="audience_id is required")

    data = await fetch_audience_companies(user["id"], audience_id)
    companies = data.get("companies", data.get("data", []))

    valid_urls = []
    seen = set()
    for company in companies:
        domain = (company.get("domain") or company.get("website") or "").strip()
        if not domain or domain in seen:
            continue
        url = normalize_url(domain)
        try:
            url = validate_company_url(url)
        except ValueError:
            continue
        seen.add(domain)
        valid_urls.append(url)
        if len(valid_urls) >= 100:
            break

    if not valid_urls:
        raise HTTPException(status_code=400, detail="No valid domains found in Ocean.io audience")

    usage = await get_user_usage(user["id"])
    is_admin = usage.get("is_admin", False)
    needed = len(valid_urls) * 100
    if not is_admin and usage.get("bonus_credits", 0) < needed:
        raise HTTPException(
            status_code=402,
            detail=f"Not enough credits. Need {len(valid_urls)}, have {usage.get('bonus_credits', 0) // 100}."
        )

    if not is_admin:
        await use_credit(user["id"], cents=needed)

    lst = await create_list(user["id"], api_key_id=None, name=list_name)
    await add_list_accounts(lst["id"], valid_urls)
    await update_list_credits(lst["id"], needed)

    create_tracked_task(
        run_list_analysis(lst["id"], user["id"], api_key_id=None, is_admin=is_admin),
        name=f"list-{lst['id']}",
    )

    return JSONResponse({"success": True, "list_id": lst["id"]})


# ==========================================================================
# Slack
# ==========================================================================

@router.post("/integrations/slack/connect")
async def slack_connect(request: Request, user: dict = Depends(require_auth)):
    """Save Slack webhook URL after validation."""
    from services.notifications import validate_webhook_url
    from database import upsert_integration

    body = await request.json()
    webhook_url = body.get("webhook_url", "").strip()
    if not webhook_url:
        raise HTTPException(status_code=400, detail="Webhook URL is required")

    valid = await validate_webhook_url(webhook_url)
    if not valid:
        raise HTTPException(status_code=400, detail="Invalid Slack webhook URL — test message failed")

    await upsert_integration(
        user_id=user["id"],
        provider="slack",
        access_token=webhook_url,
    )

    return JSONResponse({"success": True})


@router.post("/integrations/slack/disconnect")
async def slack_disconnect(request: Request, user: dict = Depends(require_auth)):
    """Disconnect Slack integration."""
    from database import delete_integration
    await delete_integration(user["id"], "slack")
    return RedirectResponse(url="/integrations", status_code=303)


@router.post("/integrations/slack/test")
async def slack_test(request: Request, user: dict = Depends(require_auth)):
    """Send a test Slack notification."""
    from services.notifications import send_slack_notification
    from database import get_integration

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
