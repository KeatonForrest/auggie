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
from database import (
    init_database, close_database, save_document, get_document,
    get_all_documents, update_user_profile, increment_user_searches,
    get_user_usage, get_user_materials,
)
from auth import router as auth_router, get_current_user, require_auth, require_onboarding
from billing import router as billing_router

settings = get_settings()

FREE_SEARCH_LIMIT = 5   # Free tier: 5 searches total, no reset
PRO_SEARCH_LIMIT = 25   # Pro tier: 25 searches/month, resets on payment


def get_search_limit(user: dict) -> int:
    """Return search limit based on subscription status."""
    if user.get("subscription_status") == "active":
        return PRO_SEARCH_LIMIT
    return FREE_SEARCH_LIMIT


def normalize_url(url: str) -> str:
    """Add https:// if no protocol specified."""
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

templates = Jinja2Templates(directory="templates")

# Services (instantiated once, reused for all requests)
firecrawl_service = FirecrawlService()
claude_service = ClaudeService()
wappalyzer_service = WappalyzerService()
news_service = NewsService()

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
            "searches_used": usage["searches_used"],
            "search_limit": get_search_limit(user),
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
    product_name: str = Form(...),
    product_description: str = Form(...),
    problems_solved: str = Form(...),
    differentiators: str = Form(""),
    target_company_size: list[str] = Form([]),
    target_industries: str = Form(""),
    target_personas: str = Form(""),
    competitors: str = Form(""),
    user: dict = Depends(require_auth),
):
    """Save onboarding data and redirect to dashboard."""
    # Join checkbox values into comma-separated string
    target_size_str = ", ".join(target_company_size) if target_company_size else ""

    await update_user_profile(
        user_id=user["id"],
        company_name=company_name,
        product_name=product_name,
        product_description=product_description,
        problems_solved=problems_solved,
        differentiators=differentiators,
        target_company_size=target_size_str,
        target_industries=target_industries,
        target_personas=target_personas,
        competitors=competitors,
    )
    return RedirectResponse(url="/", status_code=302)


@app.post("/research", response_class=HTMLResponse)
async def create_research(
    request: Request,
    company_url: str = Form(...),
    user: dict = Depends(require_onboarding),
):
    """Generate a research document for a company."""
    # Normalize URL (add https:// if missing)
    company_url = normalize_url(company_url)

    # Check usage limit
    usage = await get_user_usage(user["id"])
    search_limit = get_search_limit(user)
    if usage["searches_used"] >= search_limit:
        raise HTTPException(
            status_code=402,
            detail="Search limit reached. Please upgrade to continue."
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
        )

        # Save document and increment usage
        doc_id = await save_document(document, user_id=user["id"])
        document.id = doc_id
        await increment_user_searches(user["id"])

        recent_docs = await get_all_documents(user_id=user["id"], limit=10)
        usage = await get_user_usage(user["id"])

        return templates.TemplateResponse(
            "document.html",
            {
                "request": request,
                "user": user,
                "document": document,
                "recent_docs": recent_docs,
                "searches_used": usage["searches_used"],
                "search_limit": search_limit,
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

    return templates.TemplateResponse(
        "document.html",
        {
            "request": request,
            "user": user,
            "document": document,
            "recent_docs": recent_docs,
            "searches_used": usage["searches_used"],
            "search_limit": get_search_limit(user),
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
# API Endpoints (for future use)
# =============================================================================

@app.post("/api/research", response_model=ResearchResponse)
async def api_create_research(
    request: ResearchRequest,
    user: dict = Depends(require_onboarding),
):
    """API endpoint for generating research (JSON in/out)."""
    company_url = normalize_url(str(request.company_url))

    usage = await get_user_usage(user["id"])
    if usage["searches_used"] >= get_search_limit(user):
        return ResearchResponse(success=False, error="Search limit reached")

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
        )
        doc_id = await save_document(document, user_id=user["id"])
        document.id = doc_id
        await increment_user_searches(user["id"])
        return ResearchResponse(success=True, document=document)

    except Exception as e:
        return ResearchResponse(success=False, error=str(e))


@app.get("/api/documents", response_model=list[ResearchDocument])
async def api_list_documents(user: dict = Depends(require_auth)):
    """List all saved research documents for the current user."""
    return await get_all_documents(user_id=user["id"])


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
            "searches_used": usage["searches_used"],
            "search_limit": get_search_limit(user),
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
