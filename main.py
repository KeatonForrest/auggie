"""
main.py - FastAPI Application Entry Point

Run: uvicorn main:app --reload
Open: http://localhost:8000
Docs: http://localhost:8000/docs
"""

import time
from contextlib import asynccontextmanager
from io import BytesIO

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
)
from auth import router as auth_router, get_current_user, require_auth, require_onboarding
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
    )
    return RedirectResponse(url="/settings?saved=true", status_code=302)


@app.post("/research", response_class=HTMLResponse)
async def create_research(
    request: Request,
    company_url: str = Form(...),
    user: dict = Depends(require_onboarding),
):
    """Generate a research document for a company."""
    # Validate and normalize URL (SSRF protection)
    try:
        company_url = validate_company_url(company_url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Check and reserve credit upfront (admins have unlimited)
    usage = await get_user_usage(user["id"])
    is_admin = usage.get("is_admin", False)
    if not is_admin:
        reserved = await use_credit(user["id"])
        if not reserved:
            raise HTTPException(
                status_code=402,
                detail="No credits remaining. Buy more credits to continue researching."
            )

    try:
        print(f"[{user['email']}] Scraping {company_url}...")
        scraped_content = await firecrawl_service.scrape_company(company_url)

        print("Detecting technologies across domains...")
        tech_by_domain = await wappalyzer_service.analyze_multiple_domains(
            main_url=company_url,
            main_html=scraped_content.homepage_html
        )
        total_tech = sum(len(t.technologies) for t in tech_by_domain.values())
        print(f"Detected {total_tech} technologies across {len(tech_by_domain)} domains")

        # Parallel data collection
        retrieved_materials = await collect_enrichment_data(
            scraped_content, company_url, user["id"], verbose=True,
        )

        print("Generating research document...")
        document = await claude_service.generate_research_document(
            company_url=company_url,
            scraped=scraped_content,
            product_context=user["product_context"],  # From user profile!
            tech_by_domain=tech_by_domain,
            retrieved_materials=retrieved_materials,  # v2: Include materials
            seller_company=user.get("company_name", ""),  # For competitor detection
            target_personas=user.get("target_personas", ""),
            target_industries=user.get("target_industries", ""),
            problems_solved=user.get("problems_solved", ""),
        )

        # Save document (credit already deducted)
        doc_id = await save_document(document, user_id=user["id"])
        document.id = doc_id

        recent_docs = await get_all_documents(user_id=user["id"], limit=10)
        usage = await get_user_usage(user["id"])

        return templates.TemplateResponse(
            "document.html",
            {
                "request": request,
                "user": user,
                "document": document,
                "recent_docs": recent_docs,
                "credits": usage.get("bonus_credits", 0) / 100,
                "is_admin": usage.get("is_admin", False),
                "enriched_contacts": [],
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        if not is_admin:
            await refund_credit(user["id"])
        print(f"Error generating research: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
        }
    )


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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
