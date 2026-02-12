"""Research routes: start research, job progress, polling, duplicate check, document view, feedback, outreach, enrichment."""

import re
import logging
from io import BytesIO
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Depends, Form, File, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, StreamingResponse

from auth import get_current_user, require_auth, require_onboarding
from models import ResearchRequest, ResearchResponse, ResearchDocument
from database import (
    save_document, get_document, get_all_documents,
    get_user_usage, use_credit, refund_credit,
    save_enriched_contacts, get_enriched_contacts,
    get_research_job, check_duplicate_research,
    save_feedback, get_feedback,
)
from db.documents import get_document_by_id
from db.jobs import create_job_with_credit, create_research_job
from services.instances import firecrawl_service, claude_service, wappalyzer_service, writing_service, vision_service
from services.collect import collect_enrichment_data
from api.validation import validate_company_url
from api.tasks import create_tracked_task
from routes._helpers import templates, logger, _build_target_titles, settings

router = APIRouter()


@router.post("/research/start")
async def start_research(
    request: Request,
    company_url: str = Form(...),
    watch: str = Form(None),
    user: dict = Depends(require_onboarding),
):
    """Start async research job, return JSON with job_id."""
    from api.ratelimit import research_web_limiter, get_client_ip
    research_web_limiter.check(get_client_ip(request))

    try:
        company_url = validate_company_url(company_url)
    except ValueError as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=400)

    # 24h cache: return existing document instead of re-running pipeline
    from db.documents import get_recent_document_by_url
    cached_doc_id = await get_recent_document_by_url(user["id"], company_url)
    if cached_doc_id:
        # Still add to watchlist if requested
        if watch:
            from database import create_watchlist_item
            await create_watchlist_item(user["id"], company_url, schedule="biweekly")
        return JSONResponse({"success": True, "job_id": None, "redirect": f"/document/{cached_doc_id}", "cached": True})

    usage = await get_user_usage(user["id"])
    is_admin = usage.get("is_admin", False)
    if not is_admin:
        try:
            job = await create_job_with_credit(user["id"], api_key_id=None, company_url=company_url)
        except ValueError:
            return JSONResponse({"success": False, "error": "No credits remaining."}, status_code=402)
    else:
        job = await create_research_job(user["id"], api_key_id=None, company_url=company_url)

    # Add to watchlist if requested
    if watch:
        from database import create_watchlist_item
        await create_watchlist_item(user["id"], company_url, schedule="biweekly")

    await create_tracked_task(
        "research",
        {"job_id": job["id"], "user_id": user["id"], "api_key_id": None, "company_url": company_url, "is_admin": is_admin},
        name=f"web-research-{job['id']}",
    )

    return JSONResponse({"success": True, "job_id": job["id"]})


@router.get("/research/job/{job_id}", response_class=HTMLResponse)
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


@router.get("/research/job/{job_id}/status")
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


@router.get("/research/check-duplicate")
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


@router.get("/document/{doc_id}", response_class=HTMLResponse)
async def view_document(
    request: Request,
    doc_id: int,
):
    """View a saved research document. Unauthenticated requests get OG meta + login prompt."""
    user = await get_current_user(request)

    # Unauthenticated: serve minimal page with OG meta tags for link previews
    if not user:
        from database import get_document_og_meta
        meta = await get_document_og_meta(doc_id)
        if not meta:
            raise HTTPException(status_code=404, detail="Document not found")
        return templates.TemplateResponse(
            "document_preview.html",
            {"request": request, "meta": meta, "doc_id": doc_id, "app_url": settings.app_url},
        )

    # Try owner-scoped first, then unscoped for shared links
    document = await get_document(doc_id, user_id=user["id"])
    is_owner = document is not None
    if not is_owner:
        document = await get_document_by_id(doc_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    recent_docs = await get_all_documents(user_id=user["id"], limit=10)
    usage = await get_user_usage(user["id"])
    enriched_contacts = await get_enriched_contacts(doc_id, user["id"]) if is_owner else []
    feedback = await get_feedback(doc_id, user["id"]) if is_owner else None

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
            "is_owner": is_owner,
            "app_url": settings.app_url,
        }
    )


@router.post("/document/{doc_id}/feedback")
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


@router.get("/document/{doc_id}/markdown")
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


@router.get("/document/{doc_id}/og-image.png")
async def document_og_image(doc_id: int):
    """Generate a dynamic OG image for link previews (no auth required)."""
    from database import get_document_og_meta
    from services.og_image import generate_og_image

    meta = await get_document_og_meta(doc_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Document not found")

    png_bytes = generate_og_image(
        company_name=meta["company_name"],
        opportunity_score=meta.get("opportunity_score"),
        pain_score=meta.get("pain_score"),
        fit_score=meta.get("fit_score"),
        timing_score=meta.get("timing_score"),
        score_summary=meta.get("score_summary"),
    )
    return StreamingResponse(
        BytesIO(png_bytes),
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.post("/document/{doc_id}/outreach")
async def generate_outreach(
    doc_id: int,
    screenshot: UploadFile = File(None),
    user: dict = Depends(require_onboarding),
):
    """Generate a 3-email outreach sequence from a research document."""
    document = await get_document(doc_id, user_id=user["id"])
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    try:
        # Extract persona from screenshot if provided (non-fatal)
        persona_context = ""
        if screenshot and screenshot.filename:
            try:
                image_bytes = await screenshot.read()
                if len(image_bytes) > 10 * 1024 * 1024:
                    logger.warning("Screenshot too large (%d bytes), skipping", len(image_bytes))
                elif screenshot.content_type and screenshot.content_type.startswith("image/"):
                    persona = await vision_service.extract_persona_from_screenshot(
                        image_bytes, screenshot.content_type
                    )
                    if persona:
                        persona_context = vision_service.format_persona_for_prompt(persona)
            except Exception:
                logger.warning("Failed to extract persona from screenshot", exc_info=True)

        # Retrieve relevant materials (non-fatal if unavailable)
        materials = ""
        try:
            from services.collect import _get_retrieval_service
            retrieval = _get_retrieval_service()
            if retrieval:
                materials = await retrieval.get_relevant_context(
                    user_id=user["id"],
                    company_name=document.company_name,
                    company_description=document.company_overview[:500] if document.company_overview else "",
                ) or ""
        except Exception:
            pass

        emails, subject_options = await writing_service.generate_email_sequence(
            document=document,
            product_context=user.get("product_context", ""),
            product_type=user.get("product_type", "saas"),
            retrieved_materials=materials,
            seller_company=user.get("company_name", ""),
            problems_solved=user.get("problems_solved", ""),
            persona_context=persona_context,
            custom_signals=user.get("custom_signals", ""),
        )
        return JSONResponse({
            "success": True,
            "emails": emails,
            "subject_options": subject_options,
            "markdown": writing_service.format_emails_markdown(emails),
        })
    except Exception as e:
        logger.error("Error generating outreach: %s", e)
        return JSONResponse({
            "success": False,
            "error": "Failed to generate outreach. Please try again.",
        }, status_code=500)


@router.post("/document/{doc_id}/enrich")
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
        logger.error("Error enriching contacts: %s", e)
        return JSONResponse({"success": False, "error": "Failed to enrich contacts. Please try again."}, status_code=500)


# =============================================================================
# API Endpoints (JSON in/out)
# =============================================================================

@router.post("/api/research", response_model=ResearchResponse)
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
            custom_signals=user.get("custom_signals", ""),
        )
        doc_id = await save_document(document, user_id=user["id"])
        document.id = doc_id
        return ResearchResponse(success=True, document=document)

    except Exception as e:
        logger.error("Research failed for %s: %s", company_url, e)
        if not is_admin:
            await refund_credit(user["id"])
        return ResearchResponse(success=False, error="Research failed. Please try again.")


@router.get("/api/documents", response_model=list[ResearchDocument])
async def api_list_documents(user: dict = Depends(require_auth)):
    """List all saved research documents for the current user."""
    return await get_all_documents(user_id=user["id"])
