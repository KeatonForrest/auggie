"""
main.py - FastAPI Application Entry Point

Run: uvicorn main:app --reload
Open: http://localhost:8000
Docs: http://localhost:8000/docs
"""

from contextlib import asynccontextmanager
from io import BytesIO

from fastapi import FastAPI, HTTPException, Request, Form, Depends, UploadFile, File
from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from config import get_settings
from models import ResearchRequest, ResearchResponse, ResearchDocument
from services.firecrawl import FirecrawlService
from services.claude import ClaudeService
from services.wappalyzer import WappalyzerService
from services.news import NewsService
from services.materials import MaterialsService
from services.retrieval import RetrievalService
from services.writing import WritingService
from database import (
    init_database, close_database, save_document, get_document,
    get_all_documents, update_user_profile, get_user_usage,
    get_user_materials, use_credit,
    create_api_key_record, list_api_keys, revoke_api_key,
    save_enriched_contacts, get_enriched_contacts,
)
from auth import router as auth_router, get_current_user, require_auth, require_onboarding
from billing import router as billing_router
from api.routes import router as api_v1_router

settings = get_settings()


from api.validation import validate_company_url


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
    yield
    print("Shutting down...")
    await close_database()
    print("Database connections closed.")


app = FastAPI(
    title="Auggie",
    description="AI-powered account research for sales teams",
    version="1.0.0",
    lifespan=lifespan,
)

# Session middleware for OAuth state
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret)

# Include auth routes
app.include_router(auth_router)
app.include_router(billing_router)
app.include_router(api_v1_router)

templates = Jinja2Templates(directory="templates")

# Services (instantiated once, reused for all requests)
firecrawl_service = FirecrawlService()
claude_service = ClaudeService()
wappalyzer_service = WappalyzerService()
news_service = NewsService()
writing_service = WritingService()

# v2 Materials services (lazy init to avoid errors if not configured)
materials_service = None
retrieval_service = None

def get_materials_service():
    """Get or create materials service (lazy init)."""
    global materials_service
    if materials_service is None and settings.materials_enabled:
        materials_service = MaterialsService()
    return materials_service

def get_retrieval_service():
    """Get or create retrieval service (lazy init)."""
    global retrieval_service
    if retrieval_service is None and settings.materials_enabled:
        retrieval_service = RetrievalService()
    return retrieval_service


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

    # Check credits (admins have unlimited)
    usage = await get_user_usage(user["id"])
    is_admin = usage.get("is_admin", False)
    if not is_admin and usage.get("bonus_credits", 0) <= 0:
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

        # Fetch recent news about the company
        company_name = company_url.replace("https://", "").replace("http://", "").split("/")[0].replace("www.", "")
        print(f"Fetching news for {company_name}...")
        news_content = await news_service.get_company_news(company_name)
        if news_content:
            scraped_content.news = news_content
            print(f"Found recent news articles")
        else:
            print("No recent news found")

        # v2: Retrieve relevant materials if enabled
        retrieved_materials = ""
        retrieval = get_retrieval_service()
        if retrieval:
            try:
                print("Searching for relevant sales materials...")
                retrieved_materials = await retrieval.get_relevant_context(
                    user_id=user["id"],
                    company_name=company_name,
                    company_description=scraped_content.homepage[:500] if scraped_content.homepage else "",
                )
                if retrieved_materials:
                    print(f"Found relevant materials to enhance research")
            except Exception as e:
                print(f"Materials retrieval failed (non-fatal): {e}")

        print("Generating research document...")
        document = await claude_service.generate_research_document(
            company_url=company_url,
            scraped=scraped_content,
            product_context=user["product_context"],  # From user profile!
            tech_by_domain=tech_by_domain,
            retrieved_materials=retrieved_materials,  # v2: Include materials
            seller_company=user.get("company_name", ""),  # For competitor detection
        )

        # Save document and deduct credit (skip for admins)
        doc_id = await save_document(document, user_id=user["id"])
        document.id = doc_id
        if not is_admin:
            await use_credit(user["id"])

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

    return StreamingResponse(
        BytesIO(document.full_markdown.encode()),
        media_type="text/markdown",
        headers={"Content-Disposition": f"attachment; filename={document.company_name}_research.md"}
    )


@app.get("/document/{doc_id}/pdf")
async def get_pdf(doc_id: int, user: dict = Depends(require_auth)):
    """Download document as PDF (currently returns markdown fallback)."""
    document = await get_document(doc_id, user_id=user["id"])
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    # TODO: Implement PDF generation with WeasyPrint
    return StreamingResponse(
        BytesIO(document.full_markdown.encode()),
        media_type="text/markdown",
        headers={"Content-Disposition": f"attachment; filename={document.company_name}_research.md"}
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

    # Check credits (enrichment costs 0.5 credits = 50 cents)
    usage = await get_user_usage(user["id"])
    is_admin = usage.get("is_admin", False)
    if not is_admin and usage.get("bonus_credits", 0) < 50:
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
            if not is_admin:
                await use_credit(user["id"], cents=50)

        return JSONResponse({
            "success": True,
            "contacts": contacts,
            "cached": False,
        })
    except Exception as e:
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
    if not is_admin and usage.get("bonus_credits", 0) <= 0:
        return ResearchResponse(success=False, error="No credits remaining")

    try:
        scraped_content = await firecrawl_service.scrape_company(company_url)
        tech_by_domain = await wappalyzer_service.analyze_multiple_domains(
            main_url=company_url,
            main_html=scraped_content.homepage_html
        )

        # Fetch recent news
        company_name = company_url.replace("https://", "").replace("http://", "").split("/")[0].replace("www.", "")
        news_content = await news_service.get_company_news(company_name)
        if news_content:
            scraped_content.news = news_content

        # v2: Retrieve relevant materials if enabled
        retrieved_materials = ""
        retrieval = get_retrieval_service()
        if retrieval:
            try:
                retrieved_materials = await retrieval.get_relevant_context(
                    user_id=user["id"],
                    company_name=company_name,
                    company_description=scraped_content.homepage[:500] if scraped_content.homepage else "",
                )
            except Exception:
                pass  # Non-fatal

        document = await claude_service.generate_research_document(
            company_url=company_url,
            scraped=scraped_content,
            product_context=user["product_context"],
            tech_by_domain=tech_by_domain,
            retrieved_materials=retrieved_materials,
            seller_company=user.get("company_name", ""),
        )
        doc_id = await save_document(document, user_id=user["id"])
        document.id = doc_id
        if not is_admin:
            await use_credit(user["id"])
        return ResearchResponse(success=True, document=document)

    except Exception as e:
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
    return templates.TemplateResponse(
        "api_keys.html",
        {
            "request": request,
            "user": user,
            "api_keys": keys,
            "credits": usage.get("bonus_credits", 0) / 100,
            "is_admin": usage.get("is_admin", False),
            "new_key": request.query_params.get("new_key"),
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
