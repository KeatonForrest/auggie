"""
main.py - FastAPI Application Entry Point

Run: uvicorn main:app --reload
Open: http://localhost:8000
Docs: http://localhost:8000/docs
"""

import time
from datetime import datetime
from contextlib import asynccontextmanager
from io import BytesIO
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, Form, Depends, UploadFile, File
from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from config import get_settings
from models import ResearchRequest, ResearchResponse, ResearchDocument
from services.materials import MaterialsService
from services.instances import firecrawl_service, claude_service, wappalyzer_service, writing_service
from services.collect import collect_enrichment_data, close_shared_http_client
from database import (
    init_database, close_database, save_document, get_document,
    get_all_documents, update_user_profile, get_user_usage,
    get_user_materials, use_credit, refund_credit,
    create_api_key_record, list_api_keys, revoke_api_key,
    get_api_key_usage_stats,
    save_enriched_contacts, get_enriched_contacts,
    create_list, add_list_accounts, update_list_credits,
    list_lists, get_list, get_list_accounts,
    create_research_job, get_research_job,
    check_duplicate_research, get_list_account, reset_list_account,
    get_user_webhook, upsert_webhook, delete_user_webhook,
    save_feedback, get_feedback,
)
from auth import router as auth_router, get_current_user, require_auth, require_onboarding, require_org_admin
from billing import router as billing_router
from api.routes import router as api_v1_router
from api.webhooks import router as webhooks_router

settings = get_settings()

_is_https = settings.app_url.startswith("https")


class LatencyLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.url.path == "/health":
            return await call_next(request)
        start = time.monotonic()
        response = await call_next(request)
        duration = time.monotonic() - start
        if duration > 1.0:
            print(f"SLOW {request.method} {request.url.path} -> {response.status_code} ({duration:.2f}s)")
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' https://*.googleusercontent.com data:; "
            "font-src 'self'; "
            "connect-src 'self'; "
            "frame-ancestors 'none'"
        )
        if _is_https:
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        return response


import re

from api.validation import validate_company_url
from api.tasks import create_tracked_task


def normalize_url(url: str) -> str:
    """Add https:// if no protocol specified. For non-research URLs."""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database on startup, close on shutdown."""
    print("Initializing database...")
    await init_database()
    print("Database ready!")
    # Warn if default session secret is used in non-localhost mode
    if "localhost" not in settings.app_url and settings.session_secret == "dev-secret-change-in-production":
        print("=" * 60)
        print("WARNING: Using default session secret in production!")
        print("Set SESSION_SECRET to a strong random value.")
        print("=" * 60)
    yield
    print("Shutting down...")
    await close_shared_http_client()
    await close_database()
    print("Database connections closed.")


app = FastAPI(
    title="Auggie",
    description="AI-powered account research for sales teams",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/openapi-docs",
)

# Latency logging (outermost = first to run)
app.add_middleware(LatencyLoggingMiddleware)

# Security headers
app.add_middleware(SecurityHeadersMiddleware)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.app_url],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
    allow_credentials=True,
)

# Session middleware for OAuth state
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    https_only=_is_https,
    same_site="lax",
)

# Include auth routes
app.include_router(auth_router)
app.include_router(billing_router)
app.include_router(api_v1_router)
app.include_router(webhooks_router)

templates = Jinja2Templates(directory="templates")


@app.get("/health")
async def health_check():
    """Unauthenticated health check for uptime monitors and Railway."""
    from database import _pool
    try:
        async with _pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return JSONResponse({"status": "ok", "db": "ok"})
    except Exception:
        return JSONResponse({"status": "degraded", "db": "error"}, status_code=503)

_ERROR_TITLES = {
    400: "Invalid Request",
    402: "Insufficient Credits",
    403: "Forbidden",
    404: "Not Found",
    500: "Something Went Wrong",
}

@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request: Request, exc: StarletteHTTPException):
    accept = request.headers.get("accept", "")
    if "text/html" in accept:
        title = _ERROR_TITLES.get(exc.status_code, "Error")
        detail = exc.detail or "An unexpected error occurred."
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "status_code": exc.status_code, "title": title, "detail": detail},
            status_code=exc.status_code,
        )
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

# v2 Materials services (lazy init to avoid errors if not configured)
materials_service = None

def get_materials_service():
    """Get or create materials service (lazy init)."""
    global materials_service
    if materials_service is None and settings.materials_enabled:
        materials_service = MaterialsService()
    return materials_service


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Home page - shows login or dashboard based on auth state."""
    user = await get_current_user(request)

    if not user:
        # Show landing/login page
        return templates.TemplateResponse(
            "landing.html",
            {"request": request}
        )

    if not user.get("product_context"):
        # Redirect to onboarding
        return RedirectResponse(url="/onboarding", status_code=302)

    # Show dashboard with user's documents
    recent_docs = await get_all_documents(user_id=user["id"], limit=10)
    usage = await get_user_usage(user["id"])

    # Check if user has materials (for prompt)
    show_materials_prompt = False
    if settings.materials_enabled:
        materials = await get_user_materials(user["id"])
        show_materials_prompt = len(materials) == 0

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "user": user,
            "recent_docs": recent_docs,
            "credits": usage.get("bonus_credits", 0) / 100,
            "is_admin": usage.get("is_admin", False),
            "show_materials_prompt": show_materials_prompt,
            "materials_enabled": settings.materials_enabled,
        }
    )


@app.get("/docs", response_class=HTMLResponse)
async def docs_page(request: Request):
    """Public API documentation page."""
    user = await get_current_user(request)
    return templates.TemplateResponse(
        "docs.html",
        {"request": request, "user": user}
    )


@app.get("/guides/clay-pain-based-outbound", response_class=HTMLResponse)
async def guide_clay_pain_outbound_redirect():
    """Redirect old URL to new one."""
    return RedirectResponse(url="/guides/clay-problem-signal-prospecting", status_code=301)


@app.get("/guides/clay-problem-signal-prospecting", response_class=HTMLResponse)
async def guide_clay_problem_signal(request: Request):
    """Clay problem-signal prospecting guide page."""
    user = await get_current_user(request)
    clay_template = {
        "columns": [
            {"name": "Company Website", "type": "text", "description": "The company domain to research"},
            {
                "name": "Auggie Research",
                "type": "http_request",
                "config": {
                    "method": "POST",
                    "url": "https://auggie.app/v1/clay/enrich",
                    "headers": {
                        "Authorization": "Bearer aug_your_key",
                        "Content-Type": "application/json"
                    },
                    "body": "{\"company_url\": \"{{/Company Website}}\"}"
                }
            },
            {"name": "Pain Score", "type": "extract", "path": "pain_score"},
            {"name": "Composite Score", "type": "extract", "path": "composite_score"},
            {"name": "Score Summary", "type": "extract", "path": "score_summary"},
            {"name": "Pain Reasons", "type": "extract", "path": "pain_reasons"},
            {"name": "Business Problems", "type": "extract", "path": "business_problems"},
            {"name": "Talking Points", "type": "extract", "path": "talking_points"},
            {"name": "Product Fit", "type": "extract", "path": "product_fit"},
            {"name": "Document ID", "type": "extract", "path": "document_id"}
        ],
        "filters": [
            {"column": "Pain Score", "operator": ">=", "value": 70}
        ]
    }
    return templates.TemplateResponse(
        "guide_clay_pain_outbound.html",
        {"request": request, "user": user, "clay_template_json": clay_template}
    )


@app.get("/integrations/clay", response_class=HTMLResponse)
async def integrations_clay(request: Request):
    """Clay integration landing page for marketplace listing."""
    user = await get_current_user(request)
    return templates.TemplateResponse(
        "integrations_clay.html",
        {"request": request, "user": user}
    )


# ==========================================================================
# Integrations: HubSpot + Instantly
# ==========================================================================

@app.get("/integrations", response_class=HTMLResponse)
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


@app.get("/integrations/hubspot/connect")
async def hubspot_connect(request: Request, user: dict = Depends(require_auth)):
    """Redirect to HubSpot OAuth."""
    import secrets
    from services.hubspot import get_authorize_url
    state = secrets.token_urlsafe(24)
    request.session["_hubspot_state_"] = state
    url = get_authorize_url(state)
    return RedirectResponse(url=url)


@app.get("/integrations/hubspot/callback")
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


@app.post("/integrations/hubspot/disconnect")
async def hubspot_disconnect(request: Request, user: dict = Depends(require_auth)):
    """Disconnect HubSpot integration."""
    from database import delete_integration
    await delete_integration(user["id"], "hubspot")
    return RedirectResponse(url="/integrations", status_code=303)


@app.get("/integrations/hubspot/companies")
async def hubspot_companies(request: Request, user: dict = Depends(require_onboarding)):
    """Fetch companies from HubSpot for import selection."""
    from services.hubspot import fetch_companies
    after = request.query_params.get("after")
    try:
        data = await fetch_companies(user["id"], limit=100, after=after)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"HubSpot API error: {str(e)[:200]}")
    return JSONResponse(data)


@app.post("/integrations/hubspot/import")
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


# --- Instantly ---

@app.post("/integrations/instantly/connect")
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


@app.post("/integrations/instantly/disconnect")
async def instantly_disconnect(request: Request, user: dict = Depends(require_auth)):
    """Disconnect Instantly integration."""
    from database import delete_integration
    await delete_integration(user["id"], "instantly")
    return RedirectResponse(url="/integrations", status_code=303)


@app.get("/integrations/instantly/campaigns")
async def instantly_campaigns(request: Request, user: dict = Depends(require_onboarding)):
    """List Instantly campaigns."""
    from services.instantly import list_campaigns
    try:
        campaigns = await list_campaigns(user["id"])
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Instantly API error: {str(e)[:200]}")
    return JSONResponse(campaigns)


@app.post("/lists/{list_id}/push-instantly")
async def push_to_instantly(
    request: Request,
    list_id: int,
    user: dict = Depends(require_onboarding),
):
    """Push selected accounts from a list to an Instantly campaign."""
    from services.instantly import push_accounts_to_instantly
    from database import get_enriched_contacts

    body = await request.json()
    campaign_id = body.get("campaign_id")
    account_ids = body.get("account_ids", [])

    if not campaign_id:
        raise HTTPException(status_code=400, detail="campaign_id is required")

    # Verify list ownership (org-scoped)
    lst = await get_list(list_id, user["id"])
    if not lst:
        raise HTTPException(status_code=404, detail="List not found")

    # Get accounts
    all_accounts = await get_list_accounts(list_id)
    if account_ids:
        accounts = [a for a in all_accounts if a["id"] in account_ids]
    else:
        accounts = [a for a in all_accounts if a.get("status") == "completed"]

    if not accounts:
        raise HTTPException(status_code=400, detail="No accounts to push")

    # Get contacts for each account
    contacts_by_account = {}
    for account in accounts:
        if account.get("document_id"):
            contacts = await get_enriched_contacts(account["document_id"], user["id"])
            if contacts:
                contacts_by_account[account["id"]] = contacts

    result = await push_accounts_to_instantly(
        user["id"], campaign_id, accounts, contacts_by_account,
    )

    return JSONResponse(result)


# --- Smartlead (API key) ---

@app.post("/integrations/smartlead/connect")
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


@app.post("/integrations/smartlead/disconnect")
async def smartlead_disconnect(request: Request, user: dict = Depends(require_auth)):
    """Disconnect Smartlead integration."""
    from database import delete_integration
    await delete_integration(user["id"], "smartlead")
    return RedirectResponse(url="/integrations", status_code=303)


@app.get("/integrations/smartlead/campaigns")
async def smartlead_campaigns(request: Request, user: dict = Depends(require_onboarding)):
    """List Smartlead campaigns."""
    from services.smartlead import list_campaigns
    try:
        campaigns = await list_campaigns(user["id"])
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Smartlead API error: {str(e)[:200]}")
    return JSONResponse(campaigns)


@app.post("/lists/{list_id}/push-smartlead")
async def push_to_smartlead(
    request: Request,
    list_id: int,
    user: dict = Depends(require_onboarding),
):
    """Push selected accounts from a list to a Smartlead campaign."""
    from services.smartlead import push_accounts_to_smartlead
    from database import get_enriched_contacts

    body = await request.json()
    campaign_id = body.get("campaign_id")
    account_ids = body.get("account_ids", [])

    if not campaign_id:
        raise HTTPException(status_code=400, detail="campaign_id is required")

    lst = await get_list(list_id, user["id"])
    if not lst:
        raise HTTPException(status_code=404, detail="List not found")

    all_accounts = await get_list_accounts(list_id)
    if account_ids:
        accounts = [a for a in all_accounts if a["id"] in account_ids]
    else:
        accounts = [a for a in all_accounts if a.get("status") == "completed"]

    if not accounts:
        raise HTTPException(status_code=400, detail="No accounts to push")

    contacts_by_account = {}
    for account in accounts:
        if account.get("document_id"):
            contacts = await get_enriched_contacts(account["document_id"], user["id"])
            if contacts:
                contacts_by_account[account["id"]] = contacts

    result = await push_accounts_to_smartlead(
        user["id"], campaign_id, accounts, contacts_by_account,
    )

    return JSONResponse(result)


# --- Salesforce (OAuth) ---

@app.get("/integrations/salesforce/connect")
async def salesforce_connect(request: Request, user: dict = Depends(require_auth)):
    """Redirect to Salesforce OAuth."""
    import secrets
    from services.salesforce import get_authorize_url
    state = secrets.token_urlsafe(24)
    request.session["_salesforce_state_"] = state
    url = get_authorize_url(state)
    return RedirectResponse(url=url)


@app.get("/integrations/salesforce/callback")
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


@app.post("/integrations/salesforce/disconnect")
async def salesforce_disconnect(request: Request, user: dict = Depends(require_auth)):
    """Disconnect Salesforce integration."""
    from database import delete_integration
    await delete_integration(user["id"], "salesforce")
    return RedirectResponse(url="/integrations", status_code=303)


@app.get("/integrations/salesforce/accounts")
async def salesforce_accounts(request: Request, user: dict = Depends(require_onboarding)):
    """Fetch accounts from Salesforce for import selection."""
    from services.salesforce import fetch_accounts
    offset = int(request.query_params.get("offset", "0"))
    try:
        data = await fetch_accounts(user["id"], limit=100, offset=offset)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Salesforce API error: {str(e)[:200]}")
    return JSONResponse(data)


@app.post("/integrations/salesforce/import")
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


# --- Outreach (OAuth) ---

@app.get("/integrations/outreach/connect")
async def outreach_connect(request: Request, user: dict = Depends(require_auth)):
    """Redirect to Outreach OAuth."""
    import secrets
    from services.outreach import get_authorize_url
    state = secrets.token_urlsafe(24)
    request.session["_outreach_state_"] = state
    url = get_authorize_url(state)
    return RedirectResponse(url=url)


@app.get("/integrations/outreach/callback")
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


@app.post("/integrations/outreach/disconnect")
async def outreach_disconnect(request: Request, user: dict = Depends(require_auth)):
    """Disconnect Outreach integration."""
    from database import delete_integration
    await delete_integration(user["id"], "outreach")
    return RedirectResponse(url="/integrations", status_code=303)


@app.post("/lists/{list_id}/push-outreach")
async def push_to_outreach(
    request: Request,
    list_id: int,
    user: dict = Depends(require_onboarding),
):
    """Push Auggie-generated sequences to Outreach (sequences only, no contacts)."""
    from services.outreach import push_sequences_to_outreach
    from database import get_outreach_draft

    body = await request.json()
    account_ids = body.get("account_ids", [])

    lst = await get_list(list_id, user["id"])
    if not lst:
        raise HTTPException(status_code=404, detail="List not found")

    all_accounts = await get_list_accounts(list_id)
    if account_ids:
        accounts = [a for a in all_accounts if a["id"] in account_ids]
    else:
        accounts = [a for a in all_accounts if a.get("status") == "completed"]

    if not accounts:
        raise HTTPException(status_code=400, detail="No accounts to push")

    drafts_by_account = {}
    for account in accounts:
        if account.get("document_id"):
            draft = await get_outreach_draft(account["document_id"])
            if draft and draft.get("content"):
                content = draft["content"]
                if isinstance(content, str):
                    import json
                    content = json.loads(content)
                emails = content.get("emails", [])
                if emails:
                    drafts_by_account[account["id"]] = emails

    if not drafts_by_account:
        raise HTTPException(status_code=400, detail="No written sequences found. Write sequences first.")

    result = await push_sequences_to_outreach(user["id"], accounts, drafts_by_account)
    return JSONResponse(result)


@app.get("/integrations/outreach/sequences")
async def outreach_sequences(request: Request, user: dict = Depends(require_onboarding)):
    """List Outreach sequences."""
    from services.outreach import list_sequences
    try:
        sequences = await list_sequences(user["id"])
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Outreach API error: {str(e)[:200]}")
    return JSONResponse(sequences)


# --- SalesLoft (OAuth) ---

@app.get("/integrations/salesloft/connect")
async def salesloft_connect(request: Request, user: dict = Depends(require_auth)):
    """Redirect to SalesLoft OAuth."""
    import secrets
    from services.salesloft import get_authorize_url
    state = secrets.token_urlsafe(24)
    request.session["_salesloft_state_"] = state
    url = get_authorize_url(state)
    return RedirectResponse(url=url)


@app.get("/integrations/salesloft/callback")
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


@app.post("/integrations/salesloft/disconnect")
async def salesloft_disconnect(request: Request, user: dict = Depends(require_auth)):
    """Disconnect SalesLoft integration."""
    from database import delete_integration
    await delete_integration(user["id"], "salesloft")
    return RedirectResponse(url="/integrations", status_code=303)


@app.post("/lists/{list_id}/push-salesloft")
async def push_to_salesloft(
    request: Request,
    list_id: int,
    user: dict = Depends(require_onboarding),
):
    """Push Auggie-generated sequences to SalesLoft as cadences (no contacts)."""
    from services.salesloft import push_sequences_to_salesloft
    from database import get_outreach_draft

    body = await request.json()
    account_ids = body.get("account_ids", [])

    lst = await get_list(list_id, user["id"])
    if not lst:
        raise HTTPException(status_code=404, detail="List not found")

    all_accounts = await get_list_accounts(list_id)
    if account_ids:
        accounts = [a for a in all_accounts if a["id"] in account_ids]
    else:
        accounts = [a for a in all_accounts if a.get("status") == "completed"]

    if not accounts:
        raise HTTPException(status_code=400, detail="No accounts to push")

    drafts_by_account = {}
    for account in accounts:
        if account.get("document_id"):
            draft = await get_outreach_draft(account["document_id"])
            if draft and draft.get("content"):
                content = draft["content"]
                if isinstance(content, str):
                    import json
                    content = json.loads(content)
                emails = content.get("emails", [])
                if emails:
                    drafts_by_account[account["id"]] = emails

    if not drafts_by_account:
        raise HTTPException(status_code=400, detail="No written sequences found. Write sequences first.")

    result = await push_sequences_to_salesloft(user["id"], accounts, drafts_by_account)
    return JSONResponse(result)


@app.get("/integrations/salesloft/cadences")
async def salesloft_cadences(request: Request, user: dict = Depends(require_onboarding)):
    """List SalesLoft cadences."""
    from services.salesloft import list_cadences
    try:
        cadences = await list_cadences(user["id"])
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"SalesLoft API error: {str(e)[:200]}")
    return JSONResponse(cadences)


# --- Apollo (API key) ---

@app.post("/integrations/apollo/connect")
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


@app.post("/integrations/apollo/disconnect")
async def apollo_disconnect(request: Request, user: dict = Depends(require_auth)):
    """Disconnect Apollo integration."""
    from database import delete_integration
    await delete_integration(user["id"], "apollo")
    return RedirectResponse(url="/integrations", status_code=303)


@app.get("/integrations/apollo/lists")
async def apollo_lists(request: Request, user: dict = Depends(require_onboarding)):
    """List saved Apollo lists."""
    from services.apollo import list_saved_lists
    try:
        lists = await list_saved_lists(user["id"])
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Apollo API error: {str(e)[:200]}")
    return JSONResponse(lists)


@app.post("/integrations/apollo/import")
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


# --- Ocean.io (API key) ---

@app.post("/integrations/ocean/connect")
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


@app.post("/integrations/ocean/disconnect")
async def ocean_disconnect(request: Request, user: dict = Depends(require_auth)):
    """Disconnect Ocean.io integration."""
    from database import delete_integration
    await delete_integration(user["id"], "ocean")
    return RedirectResponse(url="/integrations", status_code=303)


@app.get("/integrations/ocean/audiences")
async def ocean_audiences(request: Request, user: dict = Depends(require_onboarding)):
    """List Ocean.io audiences."""
    from services.ocean import list_audiences
    try:
        audiences = await list_audiences(user["id"])
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ocean.io API error: {str(e)[:200]}")
    return JSONResponse(audiences)


@app.post("/integrations/ocean/import")
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


# --- Slack (webhook URL) ---

@app.post("/integrations/slack/connect")
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


@app.post("/integrations/slack/disconnect")
async def slack_disconnect(request: Request, user: dict = Depends(require_auth)):
    """Disconnect Slack integration."""
    from database import delete_integration
    await delete_integration(user["id"], "slack")
    return RedirectResponse(url="/integrations", status_code=303)


@app.post("/integrations/slack/test")
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


@app.get("/onboarding", response_class=HTMLResponse)
async def onboarding_page(request: Request, user: dict = Depends(require_auth)):
    """Onboarding page to collect company info."""
    if user.get("product_context"):
        # Already onboarded, redirect to home
        return RedirectResponse(url="/", status_code=302)

    return templates.TemplateResponse(
        "onboarding.html",
        {"request": request, "user": user}
    )


@app.post("/onboarding")
async def complete_onboarding(
    request: Request,
    company_name: str = Form(...),
    product_name: str = Form(""),  # Now optional - extracted from materials
    product_description: str = Form(""),  # Now optional - extracted from materials
    problems_solved: str = Form(...),
    differentiators: str = Form(""),  # Now optional - extracted from materials
    target_company_size: list[str] = Form([]),
    target_industries: list[str] = Form([]),
    target_level: list[str] = Form([]),
    target_function: list[str] = Form([]),
    product_type: str = Form("saas"),
    user: dict = Depends(require_auth),
):
    """Save onboarding data and redirect to dashboard."""
    # Join checkbox values into comma-separated strings
    target_size_str = ", ".join(target_company_size) if target_company_size else ""
    target_industries_str = ", ".join(target_industries) if target_industries else ""

    # Combine level + function into personas string
    # e.g., "Levels: VP, Director | Functions: Sales / Revenue, Marketing"
    personas_parts = []
    if target_level:
        personas_parts.append(f"Levels: {', '.join(target_level)}")
    if target_function:
        personas_parts.append(f"Functions: {', '.join(target_function)}")
    target_personas_str = " | ".join(personas_parts) if personas_parts else ""

    await update_user_profile(
        user_id=user["id"],
        company_name=company_name,
        product_name=product_name,
        product_description=product_description,
        problems_solved=problems_solved,
        differentiators=differentiators,
        target_company_size=target_size_str,
        target_industries=target_industries_str,
        target_personas=target_personas_str,
        competitors="",  # No longer collected in onboarding
        product_type=product_type,
    )
    return RedirectResponse(url="/", status_code=302)


def parse_personas_string(personas_str: str) -> tuple[list[str], list[str]]:
    """Parse stored personas string back into levels and functions lists."""
    levels = []
    functions = []
    if not personas_str:
        return levels, functions

    # Format: "Levels: VP, Director | Functions: Sales / Revenue, Marketing"
    parts = personas_str.split(" | ")
    for part in parts:
        if part.startswith("Levels: "):
            levels = [l.strip() for l in part[8:].split(", ")]
        elif part.startswith("Functions: "):
            functions = [f.strip() for f in part[11:].split(", ")]

    return levels, functions


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    saved: bool = False,
    user: dict = Depends(require_onboarding),
):
    """Settings page to edit profile."""
    # Parse stored values back into lists for checkbox state
    selected_sizes = [s.strip() for s in (user.get("target_company_size") or "").split(", ") if s.strip()]
    selected_industries = [i.strip() for i in (user.get("target_industries") or "").split(", ") if i.strip()]
    selected_levels, selected_functions = parse_personas_string(user.get("target_personas") or "")

    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "user": user,
            "saved": saved,
            "selected_sizes": selected_sizes,
            "selected_industries": selected_industries,
            "selected_levels": selected_levels,
            "selected_functions": selected_functions,
        }
    )


@app.post("/settings")
async def save_settings(
    request: Request,
    company_name: str = Form(...),
    problems_solved: str = Form(...),
    target_company_size: list[str] = Form([]),
    target_industries: list[str] = Form([]),
    target_level: list[str] = Form([]),
    target_function: list[str] = Form([]),
    product_type: str = Form("saas"),
    user: dict = Depends(require_onboarding),
):
    """Save updated profile settings."""
    # Join checkbox values into comma-separated strings
    target_size_str = ", ".join(target_company_size) if target_company_size else ""
    target_industries_str = ", ".join(target_industries) if target_industries else ""

    # Combine level + function into personas string
    personas_parts = []
    if target_level:
        personas_parts.append(f"Levels: {', '.join(target_level)}")
    if target_function:
        personas_parts.append(f"Functions: {', '.join(target_function)}")
    target_personas_str = " | ".join(personas_parts) if personas_parts else ""

    await update_user_profile(
        user_id=user["id"],
        company_name=company_name,
        product_name=user.get("product_name") or "",
        product_description=user.get("product_description") or "",
        problems_solved=problems_solved,
        differentiators=user.get("differentiators") or "",
        target_company_size=target_size_str,
        target_industries=target_industries_str,
        target_personas=target_personas_str,
        competitors="",
        product_type=product_type,
    )
    return RedirectResponse(url="/settings?saved=true", status_code=302)


# =================================================================
# Team Management Routes
# =================================================================

@app.get("/settings/team", response_class=HTMLResponse)
async def team_settings(
    request: Request,
    user: dict = Depends(require_onboarding),
):
    """Team settings page — members, invites, invite form."""
    from database import get_org_members, get_pending_invites, get_org
    org_id = user.get("org_id")
    if not org_id:
        raise HTTPException(status_code=400, detail="No organization found")

    org = await get_org(org_id)
    members = await get_org_members(org_id)
    invites = await get_pending_invites(org_id) if user.get("org_role") == "admin" else []
    usage = await get_user_usage(user["id"])

    return templates.TemplateResponse(
        "team_settings.html",
        {
            "request": request,
            "user": user,
            "org": org,
            "members": members,
            "invites": invites,
            "is_admin": user.get("org_role") == "admin",
            "credits": usage.get("bonus_credits", 0) / 100,
        }
    )


@app.post("/settings/team/invite")
async def team_invite(
    request: Request,
    email: str = Form(...),
    role: str = Form("member"),
    user: dict = Depends(require_org_admin),
):
    """Send team invite (admin only)."""
    from database import create_org_invite
    if role not in ("admin", "member", "viewer"):
        role = "member"
    invite = await create_org_invite(user["org_id"], email, role, user["id"])
    return RedirectResponse(url=f"/settings/team?invited={email}", status_code=302)


@app.post("/settings/team/remove")
async def team_remove(
    request: Request,
    member_id: int = Form(...),
    user: dict = Depends(require_org_admin),
):
    """Remove a team member (admin only)."""
    from database import remove_org_member
    if member_id == user["id"]:
        raise HTTPException(status_code=400, detail="Cannot remove yourself")
    await remove_org_member(user["org_id"], member_id)
    return RedirectResponse(url="/settings/team", status_code=302)


@app.post("/settings/team/role")
async def team_change_role(
    request: Request,
    member_id: int = Form(...),
    role: str = Form(...),
    user: dict = Depends(require_org_admin),
):
    """Change team member role (admin only)."""
    from database import update_member_role
    if member_id == user["id"]:
        raise HTTPException(status_code=400, detail="Cannot change your own role")
    if role not in ("admin", "member", "viewer"):
        raise HTTPException(status_code=400, detail="Invalid role")
    await update_member_role(user["org_id"], member_id, role)
    return RedirectResponse(url="/settings/team", status_code=302)


@app.post("/settings/team/revoke-invite")
async def team_revoke_invite(
    request: Request,
    invite_id: int = Form(...),
    user: dict = Depends(require_org_admin),
):
    """Revoke a pending invite (admin only)."""
    from database import revoke_invite
    await revoke_invite(invite_id, user["org_id"])
    return RedirectResponse(url="/settings/team", status_code=302)


@app.get("/invite/{token}", response_class=HTMLResponse)
async def invite_landing(request: Request, token: str):
    """Landing page for invite links."""
    from database import get_invite_by_token
    invite = await get_invite_by_token(token)
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found or expired")
    if invite.get("accepted_at"):
        raise HTTPException(status_code=400, detail="Invite already accepted")
    if invite["expires_at"] < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Invite has expired")

    user = await get_current_user(request)
    return templates.TemplateResponse(
        "invite_accept.html",
        {
            "request": request,
            "user": user,
            "invite": invite,
            "token": token,
        }
    )


@app.post("/invite/{token}/accept")
async def accept_invite_route(request: Request, token: str):
    """Accept an invite."""
    from database import accept_invite, user_has_data
    user = await get_current_user(request)
    if not user:
        # Store token and redirect to login
        request.session["pending_invite"] = token
        return RedirectResponse(url="/auth/login", status_code=302)

    # Check if user has data in their solo org
    has_data = await user_has_data(user["id"])
    if has_data and user.get("org_id"):
        # User has data - block for now
        raise HTTPException(
            status_code=400,
            detail="You have existing research data. Please contact support to transfer your data before joining a team."
        )

    result = await accept_invite(token, user["id"])
    if not result:
        raise HTTPException(status_code=400, detail="Invite is invalid or expired")

    return RedirectResponse(url="/?joined_team=true", status_code=302)


# =================================================================
# Team Usage Dashboard
# =================================================================

@app.get("/settings/team/usage", response_class=HTMLResponse)
async def team_usage_dashboard(
    request: Request,
    user: dict = Depends(require_org_admin),
):
    """Per-member usage breakdown (admin only)."""
    from database import get_org_usage_breakdown, get_org, get_all_feedback
    org_id = user.get("org_id")
    org = await get_org(org_id)
    breakdown = await get_org_usage_breakdown(org_id, days=30)
    usage = await get_user_usage(user["id"])
    feedback_list = await get_all_feedback(limit=50)

    return templates.TemplateResponse(
        "usage_dashboard.html",
        {
            "request": request,
            "user": user,
            "org": org,
            "breakdown": breakdown,
            "credits": usage.get("bonus_credits", 0) / 100,
            "is_admin": True,
            "feedback_list": feedback_list,
        }
    )





@app.get("/document/{doc_id}", response_class=HTMLResponse)
async def view_document(
    request: Request,
    doc_id: int,
    user: dict = Depends(require_onboarding),
):
    """View a saved research document."""
    document = await get_document(doc_id, user_id=user["id"])
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    recent_docs = await get_all_documents(user_id=user["id"], limit=10)
    usage = await get_user_usage(user["id"])
    enriched_contacts = await get_enriched_contacts(doc_id, user["id"])
    feedback = await get_feedback(doc_id, user["id"])

    return templates.TemplateResponse(
        "document.html",
        {
            "request": request,
            "user": user,
            "document": document,
            "recent_docs": recent_docs,
            "credits": usage.get("bonus_credits", 0) / 100,
            "is_admin": usage.get("is_admin", False),
            "enriched_contacts": enriched_contacts,
            "feedback": feedback,
        }
    )


@app.post("/document/{doc_id}/feedback")
async def submit_feedback(
    doc_id: int,
    is_positive: bool = Form(...),
    comment: Optional[str] = Form(None),
    user: dict = Depends(require_auth),
):
    """Submit thumbs up/down feedback on a research document."""
    document = await get_document(doc_id, user_id=user["id"])
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    await save_feedback(doc_id, user["id"], is_positive, comment)
    return JSONResponse({"success": True})


@app.get("/document/{doc_id}/markdown")
async def get_markdown(doc_id: int, user: dict = Depends(require_auth)):
    """Download document as markdown file."""
    document = await get_document(doc_id, user_id=user["id"])
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    safe_name = re.sub(r'[^\w\s\-.]', '', document.company_name)
    return StreamingResponse(
        BytesIO(document.full_markdown.encode()),
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}_research.md"'}
    )



# =============================================================================
# Outreach Writing Endpoints
# =============================================================================

@app.post("/document/{doc_id}/outreach")
async def generate_outreach(
    doc_id: int,
    user: dict = Depends(require_onboarding),
):
    """Generate a 3-email outreach sequence from a research document."""
    document = await get_document(doc_id, user_id=user["id"])
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    try:
        emails = await writing_service.generate_email_sequence(
            document=document,
            product_context=user.get("product_context", ""),
            product_type=user.get("product_type", "saas"),
        )
        return JSONResponse({
            "success": True,
            "emails": emails,
            "markdown": writing_service.format_emails_markdown(emails),
        })
    except Exception as e:
        print(f"Error generating outreach: {e}")
        return JSONResponse({
            "success": False,
            "error": str(e),
        }, status_code=500)


@app.post("/document/{doc_id}/enrich")
async def enrich_document_contacts(
    doc_id: int,
    user: dict = Depends(require_onboarding),
):
    """Enrich contacts for a research document using LeadMagic."""
    from services.leadmagic import LeadMagicService
    leadmagic = LeadMagicService()

    if not leadmagic.is_configured():
        return JSONResponse({"success": False, "error": "Contact enrichment is not yet configured."})

    document = await get_document(doc_id, user_id=user["id"])
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    # Check if already enriched
    existing = await get_enriched_contacts(doc_id, user["id"])
    if existing:
        return JSONResponse({"success": True, "contacts": existing, "cached": True})

    # Reserve credit upfront (enrichment costs 0.5 credits = 50 cents)
    usage = await get_user_usage(user["id"])
    is_admin = usage.get("is_admin", False)
    if not is_admin:
        reserved = await use_credit(user["id"], cents=50)
        if not reserved:
            return JSONResponse({"success": False, "error": "No credits remaining"})

    # Build target titles from user's ICP settings
    target_titles = _build_target_titles(user)

    company_domain = document.company_url.replace("https://", "").replace("http://", "").split("/")[0].replace("www.", "")

    try:
        contacts = await leadmagic.enrich_contacts(
            company_domain=company_domain,
            company_name=document.company_name,
            target_titles=target_titles,
        )

        if contacts:
            await save_enriched_contacts(doc_id, user["id"], contacts)

        return JSONResponse({
            "success": True,
            "contacts": contacts,
            "cached": False,
        })
    except Exception as e:
        if not is_admin:
            await refund_credit(user["id"], cents=50)
        print(f"Error enriching contacts: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


def _build_target_titles(user: dict) -> list[str]:
    """Build a list of target job titles from user's ICP settings."""
    # Parse from stored personas string: "Levels: VP, Director | Functions: Engineering / Product"
    levels, functions = parse_personas_string(user.get("target_personas") or "")

    # Map to common job titles
    title_map = {
        "C-Suite": {"Sales / Revenue": "CRO", "Marketing": "CMO", "Engineering / Product": "CTO",
                     "Finance / Accounting": "CFO", "Operations": "COO", "IT / Security": "CISO",
                     "HR / People": "CHRO", "Customer Success": "CCO", "Legal": "General Counsel"},
        "VP": {"Sales / Revenue": "VP Sales", "Marketing": "VP Marketing", "Engineering / Product": "VP Engineering",
               "Finance / Accounting": "VP Finance", "Operations": "VP Operations", "IT / Security": "VP IT",
               "HR / People": "VP People", "Customer Success": "VP Customer Success", "Legal": "VP Legal"},
        "Director": {"Sales / Revenue": "Director of Sales", "Marketing": "Director of Marketing",
                     "Engineering / Product": "Director of Engineering", "Finance / Accounting": "Director of Finance",
                     "Operations": "Director of Operations", "IT / Security": "Director of IT",
                     "HR / People": "Director of HR", "Customer Success": "Director of Customer Success"},
    }

    titles = []
    for level in levels:
        if level in title_map:
            for func in functions:
                if func in title_map[level]:
                    titles.append(title_map[level][func])

    # Fallback: if no ICP configured, search common decision-maker titles
    if not titles:
        titles = ["CTO", "VP Engineering", "VP Sales", "CEO"]

    # Cap at 5 to control LeadMagic costs
    return titles[:5]


# =============================================================================
# API Endpoints (for future use)
# =============================================================================

@app.post("/api/research", response_model=ResearchResponse)
async def api_create_research(
    request: ResearchRequest,
    user: dict = Depends(require_onboarding),
):
    """API endpoint for generating research (JSON in/out)."""
    try:
        company_url = validate_company_url(str(request.company_url))
    except ValueError as e:
        return ResearchResponse(success=False, error=str(e))

    usage = await get_user_usage(user["id"])
    is_admin = usage.get("is_admin", False)
    if not is_admin:
        reserved = await use_credit(user["id"])
        if not reserved:
            return ResearchResponse(success=False, error="No credits remaining")

    try:
        scraped_content = await firecrawl_service.scrape_company(company_url)
        tech_by_domain = await wappalyzer_service.analyze_multiple_domains(
            main_url=company_url,
            main_html=scraped_content.homepage_html
        )

        retrieved_materials = await collect_enrichment_data(
            scraped_content, company_url, user["id"],
        )

        document = await claude_service.generate_research_document(
            company_url=company_url,
            scraped=scraped_content,
            product_context=user["product_context"],
            tech_by_domain=tech_by_domain,
            retrieved_materials=retrieved_materials,
            seller_company=user.get("company_name", ""),
            target_personas=user.get("target_personas", ""),
            target_industries=user.get("target_industries", ""),
            problems_solved=user.get("problems_solved", ""),
            product_type=user.get("product_type", "saas"),
        )
        doc_id = await save_document(document, user_id=user["id"])
        document.id = doc_id
        return ResearchResponse(success=True, document=document)

    except Exception as e:
        if not is_admin:
            await refund_credit(user["id"])
        return ResearchResponse(success=False, error=str(e))


@app.get("/api/documents", response_model=list[ResearchDocument])
async def api_list_documents(user: dict = Depends(require_auth)):
    """List all saved research documents for the current user."""
    return await get_all_documents(user_id=user["id"])


# =============================================================================
# API Keys Management (UI)
# =============================================================================

@app.get("/api-keys", response_class=HTMLResponse)
async def api_keys_page(request: Request, user: dict = Depends(require_auth)):
    """API keys management page."""
    keys = await list_api_keys(user["id"])
    usage = await get_user_usage(user["id"])
    usage_stats = await get_api_key_usage_stats(user["id"])
    webhook = await get_user_webhook(user["id"])
    return templates.TemplateResponse(
        "api_keys.html",
        {
            "request": request,
            "user": user,
            "api_keys": keys,
            "usage_stats": usage_stats,
            "credits": usage.get("bonus_credits", 0) / 100,
            "is_admin": usage.get("is_admin", False),
            "new_key": request.query_params.get("new_key"),
            "webhook": webhook,
            "webhook_secret": request.query_params.get("webhook_secret"),
        }
    )


@app.post("/api-keys/create")
async def create_api_key_route(request: Request, name: str = Form("Default"), user: dict = Depends(require_auth)):
    """Create a new API key."""
    from api.keys import generate_api_key
    raw_key, key_hash, prefix = generate_api_key()
    await create_api_key_record(user["id"], key_hash, prefix, name)
    return RedirectResponse(url=f"/api-keys?new_key={raw_key}", status_code=303)


@app.post("/api-keys/{key_id}/revoke")
async def revoke_api_key_route(key_id: int, user: dict = Depends(require_auth)):
    """Revoke an API key."""
    await revoke_api_key(key_id, user["id"])
    return RedirectResponse(url="/api-keys", status_code=303)


@app.post("/api-keys/webhook")
async def create_webhook_route(request: Request, webhook_url: str = Form(...), user: dict = Depends(require_auth)):
    """Register a webhook URL."""
    import secrets as _secrets
    secret = _secrets.token_hex(32)
    await upsert_webhook(user["id"], webhook_url, secret)
    return RedirectResponse(url=f"/api-keys?webhook_secret={secret}", status_code=303)


@app.post("/api-keys/webhook/delete")
async def delete_webhook_route(user: dict = Depends(require_auth)):
    """Delete user's webhook."""
    await delete_user_webhook(user["id"])
    return RedirectResponse(url="/api-keys", status_code=303)


# =============================================================================
# Materials Endpoints (v2)
# =============================================================================

@app.get("/materials", response_class=HTMLResponse)
async def materials_page(request: Request, user: dict = Depends(require_auth)):
    """Materials management page."""
    if not settings.materials_enabled:
        raise HTTPException(status_code=404, detail="Materials feature not enabled")

    materials = await get_user_materials(user["id"])
    usage = await get_user_usage(user["id"])

    return templates.TemplateResponse(
        "materials.html",
        {
            "request": request,
            "user": user,
            "materials": materials,
            "credits": usage.get("bonus_credits", 0) / 100,
            "is_admin": usage.get("is_admin", False),
        }
    )


@app.post("/materials/upload")
async def upload_material(
    file: UploadFile = File(...),
    material_type: str = Form("other"),
    user: dict = Depends(require_auth),
):
    """Upload a new material file."""
    if not settings.materials_enabled:
        return JSONResponse({"success": False, "error": "Materials feature not enabled"})

    service = get_materials_service()
    if not service:
        return JSONResponse({"success": False, "error": "Materials service not configured"})

    try:
        material = await service.upload_material(
            user_id=user["id"],
            file=file.file,
            filename=file.filename,
            material_type=material_type
        )
        # Convert datetime to string for JSON serialization
        if material.get("created_at"):
            material["created_at"] = material["created_at"].isoformat()
        if material.get("updated_at"):
            material["updated_at"] = material["updated_at"].isoformat()
        return JSONResponse({"success": True, "material": material})
    except ValueError as e:
        return JSONResponse({"success": False, "error": str(e)})
    except Exception as e:
        print(f"Material upload error: {e}")
        return JSONResponse({"success": False, "error": "Upload failed. Please try again."})


@app.delete("/materials/{material_id}")
async def delete_material(
    material_id: int,
    user: dict = Depends(require_auth),
):
    """Delete a material and its chunks."""
    if not settings.materials_enabled:
        return JSONResponse({"success": False, "error": "Materials feature not enabled"})

    service = get_materials_service()
    if not service:
        return JSONResponse({"success": False, "error": "Materials service not configured"})

    deleted = await service.delete_material(material_id, user["id"])
    return JSONResponse({"success": deleted})


@app.get("/materials/{material_id}/preview")
async def preview_material(
    material_id: int,
    user: dict = Depends(require_auth),
):
    """Return first 5 chunks of a material as preview text."""
    from database import get_material_preview, get_material
    mat = await get_material(material_id, user["id"])
    if not mat:
        raise HTTPException(status_code=404, detail="Material not found")
    if mat["status"] != "ready":
        return JSONResponse({"content": "Material is not ready for preview."})
    content = await get_material_preview(material_id, user["id"])
    return JSONResponse({"content": content})


@app.post("/materials/{material_id}/reprocess")
async def reprocess_material(
    material_id: int,
    user: dict = Depends(require_auth),
):
    """Reprocess a failed material."""
    if not settings.materials_enabled:
        return JSONResponse({"success": False, "error": "Materials feature not enabled"})

    service = get_materials_service()
    if not service:
        return JSONResponse({"success": False, "error": "Materials service not configured"})

    success = await service.reprocess_material(material_id, user["id"])
    return JSONResponse({"success": success})


@app.get("/api/materials")
async def api_list_materials(user: dict = Depends(require_auth)):
    """API: List user's materials."""
    if not settings.materials_enabled:
        return {"materials": [], "enabled": False}

    materials = await get_user_materials(user["id"])
    return {"materials": materials, "enabled": True}


# =============================================================================
# Lists Endpoints (CSV Upload)
# =============================================================================

@app.get("/lists", response_class=HTMLResponse)
async def lists_page(request: Request, user: dict = Depends(require_onboarding)):
    """Upload page + table of user's recent lists."""
    usage = await get_user_usage(user["id"])
    recent = await list_lists(user["id"])
    return templates.TemplateResponse(
        "lists.html",
        {
            "request": request,
            "user": user,
            "lists": recent,
            "credits": usage.get("bonus_credits", 0) / 100,
            "is_admin": usage.get("is_admin", False),
        }
    )


@app.post("/lists/upload")
async def upload_list_csv(
    request: Request,
    file: UploadFile = File(...),
    list_name: str = Form(""),
    user: dict = Depends(require_onboarding),
):
    """Parse CSV, validate URLs, check credits, create list, start analysis."""
    from api.ratelimit import upload_limiter, get_client_ip
    upload_limiter.check(get_client_ip(request))

    import csv
    from io import StringIO
    from api.jobs import run_list_analysis

    # Validate file
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Please upload a .csv file.")

    contents = await file.read()
    if len(contents) > 1_048_576:
        raise HTTPException(status_code=400, detail="File too large (max 1MB).")

    # Parse CSV
    text = contents.decode("utf-8", errors="replace")
    reader = csv.reader(StringIO(text))
    rows = list(reader)
    if not rows:
        raise HTTPException(status_code=400, detail="CSV file is empty.")

    # Detect domain column
    header = rows[0]
    domain_col = None
    recognized = {"domain", "url", "website", "company_url", "company"}
    for i, col in enumerate(header):
        if col.strip().lower() in recognized:
            domain_col = i
            break

    if domain_col is not None:
        data_rows = rows[1:]  # skip header
    else:
        domain_col = 0  # treat first column as domains
        # If first row looks like a URL/domain, include it
        data_rows = rows

    # Extract and normalize URLs
    raw_urls = []
    for row in data_rows:
        if domain_col < len(row) and row[domain_col].strip():
            raw_urls.append(row[domain_col].strip())

    # Normalize and validate
    valid_urls = []
    seen = set()
    for raw in raw_urls:
        url = normalize_url(raw)
        try:
            url = validate_company_url(url)
        except ValueError:
            continue
        if url not in seen:
            seen.add(url)
            valid_urls.append(url)
        if len(valid_urls) >= 100:
            break

    if not valid_urls:
        raise HTTPException(status_code=400, detail="No valid domains found in CSV.")

    # Check credits
    usage = await get_user_usage(user["id"])
    is_admin = usage.get("is_admin", False)
    needed = len(valid_urls) * 100  # cents
    if not is_admin and usage.get("bonus_credits", 0) < needed:
        raise HTTPException(
            status_code=402,
            detail=f"Not enough credits. Need {len(valid_urls)}, have {usage.get('bonus_credits', 0) // 100}."
        )

    # Reserve credits
    if not is_admin:
        await use_credit(user["id"], cents=needed)

    # Create list
    name = list_name.strip() or (file.filename.rsplit(".", 1)[0] if file.filename else "Uploaded List")
    lst = await create_list(user["id"], api_key_id=None, name=name)
    await add_list_accounts(lst["id"], valid_urls)
    await update_list_credits(lst["id"], needed)

    # Start analysis in background
    create_tracked_task(run_list_analysis(lst["id"], user["id"], api_key_id=None, is_admin=is_admin), name=f"list-{lst['id']}")

    return RedirectResponse(url=f"/lists/{lst['id']}", status_code=303)


@app.get("/lists/{list_id}", response_class=HTMLResponse)
async def view_list(
    request: Request,
    list_id: int,
    min_score: int = 0,
    sort: str = "composite_score",
    user: dict = Depends(require_onboarding),
):
    """Results page with sortable/filterable score table."""
    lst = await get_list(list_id, user["id"])
    if not lst:
        raise HTTPException(status_code=404, detail="List not found")

    accounts = await get_list_accounts(
        list_id,
        min_composite=min_score if min_score > 0 else None,
        sort_by=sort,
    )
    usage = await get_user_usage(user["id"])

    # Check if Instantly is connected
    from database import get_integration
    instantly_integration = await get_integration(user["id"], "instantly")
    smartlead_integration = await get_integration(user["id"], "smartlead")
    outreach_integration = await get_integration(user["id"], "outreach")
    salesloft_integration = await get_integration(user["id"], "salesloft")

    # Pipeline step counts (computed server-side)
    scored_count = len([a for a in accounts if a.get("status") == "completed"])
    enriched_count = len([a for a in accounts if a.get("enrichment_status") == "completed"])
    written_count = len([a for a in accounts if a.get("outreach_status") == "completed"])
    pushed_count = len([a for a in accounts if a.get("pushed_to") and isinstance(a["pushed_to"], dict) and a["pushed_to"] != {}])

    return templates.TemplateResponse(
        "list_view.html",
        {
            "request": request,
            "user": user,
            "list": lst,
            "accounts": accounts,
            "min_score": min_score,
            "sort": sort,
            "credits": usage.get("bonus_credits", 0) / 100,
            "is_admin": usage.get("is_admin", False),
            "instantly_connected": instantly_integration is not None,
            "smartlead_connected": smartlead_integration is not None,
            "outreach_connected": outreach_integration is not None,
            "salesloft_connected": salesloft_integration is not None,
            "scored_count": scored_count,
            "enriched_count": enriched_count,
            "written_count": written_count,
            "pushed_count": pushed_count,
        }
    )


# =============================================================================
# Research Progress (async job + polling)
# =============================================================================

@app.post("/research/start")
async def start_research(
    request: Request,
    company_url: str = Form(...),
    user: dict = Depends(require_onboarding),
):
    """Start async research job, return JSON with job_id."""
    from api.ratelimit import research_web_limiter, get_client_ip
    research_web_limiter.check(get_client_ip(request))

    try:
        company_url = validate_company_url(company_url)
    except ValueError as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=400)

    usage = await get_user_usage(user["id"])
    is_admin = usage.get("is_admin", False)
    if not is_admin:
        reserved = await use_credit(user["id"])
        if not reserved:
            return JSONResponse({"success": False, "error": "No credits remaining."}, status_code=402)

    job = await create_research_job(user["id"], api_key_id=None, company_url=company_url)

    from api.jobs import run_research_job
    create_tracked_task(
        run_research_job(job["id"], user["id"], api_key_id=None, company_url=company_url, is_admin=is_admin),
        name=f"web-research-{job['id']}",
    )

    return JSONResponse({"success": True, "job_id": job["id"]})


@app.get("/research/job/{job_id}", response_class=HTMLResponse)
async def research_progress_page(
    request: Request,
    job_id: int,
    user: dict = Depends(require_onboarding),
):
    """Render research progress page."""
    job = await get_research_job(job_id, user["id"])
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # If already completed, redirect directly
    if job["status"] == "completed" and job.get("document_id"):
        return RedirectResponse(url=f"/document/{job['document_id']}", status_code=302)

    recent_docs = await get_all_documents(user_id=user["id"], limit=10)
    usage = await get_user_usage(user["id"])
    return templates.TemplateResponse(
        "research_progress.html",
        {
            "request": request,
            "user": user,
            "job": job,
            "recent_docs": recent_docs,
            "credits": usage.get("bonus_credits", 0) / 100,
            "is_admin": usage.get("is_admin", False),
        }
    )


@app.get("/research/job/{job_id}/status")
async def research_job_status(
    job_id: int,
    user: dict = Depends(require_auth),
):
    """Polling endpoint for research job status."""
    job = await get_research_job(job_id, user["id"])
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return JSONResponse({
        "status": job["status"],
        "progress": job.get("progress"),
        "document_id": job.get("document_id"),
        "error_message": job.get("error_message"),
    })


# =============================================================================
# Duplicate Research Check
# =============================================================================

@app.get("/research/check-duplicate")
async def check_duplicate(
    company_url: str,
    user: dict = Depends(require_auth),
):
    """Check if user recently researched this URL."""
    try:
        company_url = validate_company_url(company_url)
    except ValueError:
        return JSONResponse({"exists": False})

    dup = await check_duplicate_research(user["id"], company_url, days=7)
    if dup:
        return JSONResponse({
            "exists": True,
            "document_id": dup["id"],
            "company_name": dup["company_name"],
            "created_at": dup["created_at"].isoformat(),
        })
    return JSONResponse({"exists": False})


# =============================================================================
# CSV Export
# =============================================================================

@app.get("/lists/{list_id}/export")
async def export_list_csv(
    list_id: int,
    user: dict = Depends(require_onboarding),
):
    """Export list accounts as CSV."""
    import csv
    from io import StringIO

    lst = await get_list(list_id, user["id"])
    if not lst:
        raise HTTPException(status_code=404, detail="List not found")

    accounts = await get_list_accounts(list_id, limit=10000)

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Company Name", "Website", "Pain Score", "Fit Score", "Timing Score", "Composite Score", "Status"])
    for a in accounts:
        writer.writerow([
            a.get("company_name") or "",
            a.get("company_url", ""),
            a.get("pain_score") if a.get("pain_score") is not None else "",
            a.get("fit_score") if a.get("fit_score") is not None else "",
            a.get("timing_score") if a.get("timing_score") is not None else "",
            a.get("composite_score") if a.get("composite_score") is not None else "",
            a.get("status", ""),
        ])

    safe_name = re.sub(r'[^\w\s\-.]', '', lst["name"])
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}.csv"'},
    )


# =============================================================================
# Bulk List Actions
# =============================================================================

@app.post("/lists/{list_id}/export-selected")
async def export_selected_csv(
    list_id: int,
    request: Request,
    user: dict = Depends(require_onboarding),
):
    """Export selected list accounts as CSV."""
    import csv
    from io import StringIO

    body = await request.json()
    account_ids = body.get("account_ids", [])
    if not account_ids:
        raise HTTPException(status_code=400, detail="No accounts selected")

    lst = await get_list(list_id, user["id"])
    if not lst:
        raise HTTPException(status_code=404, detail="List not found")

    all_accounts = await get_list_accounts(list_id, limit=10000)
    selected = [a for a in all_accounts if a["id"] in account_ids]

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Company Name", "Website", "Pain Score", "Fit Score", "Timing Score", "Composite Score", "Status"])
    for a in selected:
        writer.writerow([
            a.get("company_name") or "",
            a.get("company_url", ""),
            a.get("pain_score") if a.get("pain_score") is not None else "",
            a.get("fit_score") if a.get("fit_score") is not None else "",
            a.get("timing_score") if a.get("timing_score") is not None else "",
            a.get("composite_score") if a.get("composite_score") is not None else "",
            a.get("status", ""),
        ])

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="selected_accounts.csv"'},
    )


@app.post("/lists/{list_id}/batch-write-sequences")
async def batch_write_sequences(
    list_id: int,
    request: Request,
    user: dict = Depends(require_onboarding),
):
    """Generate outreach sequences for accounts in a list."""
    from api.jobs import run_batch_write_sequences

    lst = await get_list(list_id, user["id"])
    if not lst:
        raise HTTPException(status_code=404, detail="List not found")

    try:
        body = await request.json()
    except Exception:
        body = {}
    account_ids = body.get("account_ids")

    create_tracked_task(
        run_batch_write_sequences(list_id, user["id"], account_ids=account_ids),
        name=f"write-seq-{list_id}",
    )

    # Count how many will be processed
    all_accounts = await get_list_accounts(list_id, limit=10000)
    if account_ids:
        queued = len([a for a in all_accounts if a["id"] in account_ids and a.get("status") == "completed" and a.get("document_id")])
    else:
        queued = len([a for a in all_accounts if a.get("status") == "completed" and a.get("document_id")])

    return JSONResponse({"success": True, "queued_count": queued})


@app.post("/lists/{list_id}/batch-enrich")
async def batch_enrich(
    list_id: int,
    request: Request,
    user: dict = Depends(require_onboarding),
):
    """Batch enrich contacts for accounts in a list."""
    lst = await get_list(list_id, user["id"])
    if not lst:
        raise HTTPException(status_code=404, detail="List not found")

    # Stub: enrichment provider not yet configured
    return JSONResponse(
        {"success": False, "error": "Contact enrichment is not yet available. This feature is coming soon."},
        status_code=422,
    )


@app.get("/lists/{list_id}/pipeline-status")
async def pipeline_status(
    list_id: int,
    user: dict = Depends(require_auth),
):
    """Get pipeline step counts for a list."""
    lst = await get_list(list_id, user["id"])
    if not lst:
        raise HTTPException(status_code=404, detail="List not found")

    all_accounts = await get_list_accounts(list_id, limit=10000)
    scored = len([a for a in all_accounts if a.get("status") == "completed"])
    enriched = len([a for a in all_accounts if a.get("enrichment_status") == "completed"])
    sequences_written = len([a for a in all_accounts if a.get("outreach_status") == "completed"])
    pushed = len([a for a in all_accounts if a.get("pushed_to") and isinstance(a["pushed_to"], dict) and a["pushed_to"] != {}])
    total = len(all_accounts)

    return JSONResponse({
        "scored": scored,
        "enriched": enriched,
        "sequences_written": sequences_written,
        "pushed": pushed,
        "total": total,
    })


@app.post("/lists/{list_id}/retry-selected")
async def retry_selected_accounts(
    list_id: int,
    request: Request,
    user: dict = Depends(require_onboarding),
):
    """Retry multiple failed list accounts."""
    from api.jobs import _run_research_pipeline
    from database import update_list_account

    body = await request.json()
    account_ids = body.get("account_ids", [])
    if not account_ids:
        return JSONResponse({"success": False, "error": "No accounts selected"}, status_code=400)

    lst = await get_list(list_id, user["id"])
    if not lst:
        raise HTTPException(status_code=404, detail="List not found")

    all_accounts = await get_list_accounts(list_id, limit=10000)
    failed = [a for a in all_accounts if a["id"] in account_ids and a["status"] == "failed"]

    if not failed:
        return JSONResponse({"success": False, "error": "No failed accounts in selection"}, status_code=400)

    # Reserve credits
    usage = await get_user_usage(user["id"])
    is_admin = usage.get("is_admin", False)
    needed = len(failed) * 100
    if not is_admin:
        reserved = await use_credit(user["id"], cents=needed)
        if not reserved:
            return JSONResponse({"success": False, "error": "Not enough credits"}, status_code=402)

    # Reset and start retries
    retried = 0
    for a in failed:
        await reset_list_account(a["id"])
        job = await create_research_job(user["id"], api_key_id=None, company_url=a["company_url"])
        await update_list_account(a["id"], "processing", research_job_id=job["id"])

        async def _run_retry(account_id=a["id"], company_url=a["company_url"], job_id=job["id"]):
            from database import update_job_status, get_document as get_doc
            try:
                doc_id = await _run_research_pipeline(user["id"], company_url)
                await update_job_status(job_id, "completed", document_id=doc_id)
                doc = await get_doc(doc_id, user["id"])
                await update_list_account(
                    account_id, "completed",
                    document_id=doc_id,
                    research_job_id=job_id,
                    pain_score=doc.pain_score,
                    fit_score=doc.fit_score,
                    timing_score=doc.timing_score,
                    composite_score=doc.opportunity_score,
                    company_name=doc.company_name,
                )
            except Exception as e:
                if not is_admin:
                    await refund_credit(user["id"])
                error_msg = str(e)[:500]
                await update_job_status(job_id, "failed", error_message=error_msg)
                await update_list_account(account_id, "failed", research_job_id=job_id, error_message=error_msg)

        create_tracked_task(_run_retry(), name=f"retry-{a['id']}")
        retried += 1

    return JSONResponse({"success": True, "retried": retried})


# =============================================================================
# Retry Failed List Items
# =============================================================================

@app.post("/lists/{list_id}/accounts/{account_id}/retry")
async def retry_list_account(
    list_id: int,
    account_id: int,
    user: dict = Depends(require_onboarding),
):
    """Retry a failed list account."""
    from api.jobs import run_research_job

    lst = await get_list(list_id, user["id"])
    if not lst:
        raise HTTPException(status_code=404, detail="List not found")

    account = await get_list_account(account_id, list_id)
    if not account:
        return JSONResponse({"success": False, "error": "Account not found"}, status_code=404)
    if account["status"] != "failed":
        return JSONResponse({"success": False, "error": "Account is not in failed state"}, status_code=400)

    usage = await get_user_usage(user["id"])
    is_admin = usage.get("is_admin", False)
    if not is_admin:
        reserved = await use_credit(user["id"])
        if not reserved:
            return JSONResponse({"success": False, "error": "No credits remaining."}, status_code=402)

    await reset_list_account(account_id)

    job = await create_research_job(user["id"], api_key_id=None, company_url=account["company_url"])

    from database import update_list_account
    await update_list_account(account_id, "processing", research_job_id=job["id"])

    async def _run_retry():
        from api.jobs import _run_research_pipeline
        from database import update_job_status, get_document as get_doc
        try:
            doc_id = await _run_research_pipeline(user["id"], account["company_url"])
            await update_job_status(job["id"], "completed", document_id=doc_id)
            doc = await get_doc(doc_id, user["id"])
            await update_list_account(
                account_id, "completed",
                document_id=doc_id,
                research_job_id=job["id"],
                pain_score=doc.pain_score,
                fit_score=doc.fit_score,
                timing_score=doc.timing_score,
                composite_score=doc.opportunity_score,
                company_name=doc.company_name,
            )
        except Exception as e:
            if not is_admin:
                await refund_credit(user["id"])
            error_msg = str(e)[:500]
            await update_job_status(job["id"], "failed", error_message=error_msg)
            await update_list_account(account_id, "failed", research_job_id=job["id"], error_message=error_msg)

    create_tracked_task(_run_retry(), name=f"retry-{account_id}")
    return JSONResponse({"success": True})


# =============================================================================
# Automation Rules
# =============================================================================

@app.get("/automations", response_class=HTMLResponse)
async def automations_page(request: Request, user: dict = Depends(require_onboarding)):
    """Automation rules management page."""
    from database import get_automation_rules, get_automation_runs
    rules = await get_automation_rules(user["id"])
    runs = await get_automation_runs(user["id"], limit=50)
    usage = await get_user_usage(user["id"])

    # Check which integrations are connected for action config
    from database import get_integration
    instantly_connected = await get_integration(user["id"], "instantly") is not None
    smartlead_connected = await get_integration(user["id"], "smartlead") is not None
    outreach_connected = await get_integration(user["id"], "outreach") is not None
    salesloft_connected = await get_integration(user["id"], "salesloft") is not None
    slack_connected = await get_integration(user["id"], "slack") is not None

    # Group runs by rule_id for easy lookup in template
    runs_by_rule = {}
    for run in runs:
        runs_by_rule.setdefault(run["rule_id"], []).append(run)

    return templates.TemplateResponse(
        "automations.html",
        {
            "request": request,
            "user": user,
            "rules": rules,
            "runs_by_rule": runs_by_rule,
            "credits": usage.get("bonus_credits", 0) / 100,
            "is_admin": usage.get("is_admin", False),
            "instantly_connected": instantly_connected,
            "smartlead_connected": smartlead_connected,
            "outreach_connected": outreach_connected,
            "salesloft_connected": salesloft_connected,
            "slack_connected": slack_connected,
        }
    )


@app.post("/automations")
async def create_automation(request: Request, user: dict = Depends(require_onboarding)):
    """Create a new automation rule."""
    from database import create_automation_rule
    body = await request.json()

    name = body.get("name", "").strip()
    trigger_event = body.get("trigger_event", "")
    conditions = body.get("conditions", {})
    action = body.get("action", "")
    action_config = body.get("action_config", {})

    if not name or not trigger_event or not action:
        raise HTTPException(status_code=400, detail="Name, trigger, and action are required")

    valid_triggers = {"list_complete", "account_scored"}
    valid_actions = {"push_instantly", "write_sequences", "notify_slack"}
    if trigger_event not in valid_triggers:
        raise HTTPException(status_code=400, detail=f"Invalid trigger: {trigger_event}")
    if action not in valid_actions:
        raise HTTPException(status_code=400, detail=f"Invalid action: {action}")

    rule = await create_automation_rule(
        user["id"], name, trigger_event, conditions, action, action_config,
    )
    return JSONResponse({"success": True, "rule_id": rule["id"]})


@app.post("/automations/{rule_id}/toggle")
async def toggle_automation(rule_id: int, request: Request, user: dict = Depends(require_onboarding)):
    """Enable or disable an automation rule."""
    from database import update_automation_rule
    body = await request.json()
    enabled = body.get("enabled", True)
    result = await update_automation_rule(rule_id, user["id"], enabled=enabled)
    if not result:
        raise HTTPException(status_code=404, detail="Rule not found")
    return JSONResponse({"success": True})


@app.post("/automations/{rule_id}/delete")
async def delete_automation(rule_id: int, user: dict = Depends(require_onboarding)):
    """Delete an automation rule."""
    from database import delete_automation_rule
    deleted = await delete_automation_rule(rule_id, user["id"])
    if not deleted:
        raise HTTPException(status_code=404, detail="Rule not found")
    return JSONResponse({"success": True})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
