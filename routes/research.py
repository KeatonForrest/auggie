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
    save_feedback, get_feedback, get_effective_product_context,
)
from db.documents import (
    get_document_by_share_token, get_share_token,
    get_document_by_slug, get_document_meta_by_slug, get_document_slug_path,
)
from db.jobs import create_job_with_credit, create_research_job
from services.instances import firecrawl_service, claude_service, tech_detection_service, writing_service, vision_service
from services.writing import SequenceValidationError
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
        slug_path = await get_document_slug_path(cached_doc_id, user["id"])
        redirect_url = slug_path or f"/document/{cached_doc_id}"
        return JSONResponse({"success": True, "job_id": None, "redirect": redirect_url, "cached": True})

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

    # If already completed, redirect directly (prefer slug URL)
    if job["status"] == "completed" and job.get("document_id"):
        slug_path = await get_document_slug_path(job["document_id"], user["id"])
        redirect_url = slug_path or f"/document/{job['document_id']}"
        return RedirectResponse(url=redirect_url, status_code=302)

    recent_docs = await get_all_documents(user_id=user["id"], limit=10)
    usage = await get_user_usage(user["id"])
    return templates.TemplateResponse(
        request,
        "research_progress.html",
        {
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
    token: Optional[str] = None,
):
    """View a saved research document. Requires ownership or a valid share token."""
    user = await get_current_user(request)

    # Unauthenticated: serve minimal page with OG meta tags for link previews
    if not user:
        from database import get_document_og_meta
        meta = await get_document_og_meta(doc_id, share_token=token)
        if not meta:
            raise HTTPException(status_code=404, detail="Document not found")
        return templates.TemplateResponse(
            request,
            "document_preview.html",
            {"meta": meta, "doc_id": doc_id, "app_url": settings.app_url},
        )

    # Try owner-scoped first
    document = await get_document(doc_id, user_id=user["id"])
    is_owner = document is not None

    # If owner, 301 redirect to slug URL for canonical links
    if is_owner:
        slug_path = await get_document_slug_path(doc_id, user["id"])
        if slug_path:
            return RedirectResponse(url=slug_path, status_code=301)

    # If not owner, require a valid share token
    if not is_owner:
        if not token:
            raise HTTPException(status_code=404, detail="Document not found")
        document = await get_document_by_share_token(doc_id, token)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    # Get the share token for owners so they can share links
    share_token = await get_share_token(doc_id, user["id"]) if is_owner else token

    recent_docs = await get_all_documents(user_id=user["id"], limit=10)
    usage = await get_user_usage(user["id"])
    enriched_contacts = await get_enriched_contacts(doc_id, user["id"]) if is_owner else []
    feedback = await get_feedback(doc_id, user["id"]) if is_owner else None

    return templates.TemplateResponse(
        request,
        "document.html",
        {
            "user": user,
            "document": document,
            "recent_docs": recent_docs,
            "credits": usage.get("bonus_credits", 0) / 100,
            "is_admin": usage.get("is_admin", False),
            "enriched_contacts": enriched_contacts,
            "feedback": feedback,
            "is_owner": is_owner,
            "share_token": share_token,
            "app_url": settings.app_url,
            "linkedin_message_enabled": getattr(settings, "linkedin_message_enabled", False),
            "linkedin_connection_note_enabled": getattr(settings, "linkedin_connection_note_enabled", False),
        }
    )


@router.get("/@{org_slug}/{doc_slug}", response_class=HTMLResponse)
async def view_document_by_slug(
    request: Request,
    org_slug: str,
    doc_slug: str,
):
    """View a research document via vanity slug URL."""
    user = await get_current_user(request)

    # Unauthenticated: serve minimal preview with OG meta
    if not user:
        meta = await get_document_meta_by_slug(org_slug, doc_slug)
        if not meta:
            raise HTTPException(status_code=404, detail="Document not found")
        return templates.TemplateResponse(
            request,
            "document_preview.html",
            {
                "meta": meta,
                "doc_id": meta["id"], "app_url": settings.app_url,
                "org_slug": org_slug, "doc_slug": doc_slug,
            },
        )

    # Authenticated: check ownership
    meta = await get_document_meta_by_slug(org_slug, doc_slug)
    if not meta:
        raise HTTPException(status_code=404, detail="Document not found")

    doc_id = meta["id"]
    is_owner = meta["user_id"] == user["id"]

    if is_owner:
        document = await get_document(doc_id, user_id=user["id"])
    else:
        # Non-owners can view slug URLs (slug URLs are the share mechanism)
        document = await get_document_by_slug(org_slug, doc_slug)

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    share_token = await get_share_token(doc_id, user["id"]) if is_owner else None
    recent_docs = await get_all_documents(user_id=user["id"], limit=10)
    usage = await get_user_usage(user["id"])
    enriched_contacts = await get_enriched_contacts(doc_id, user["id"]) if is_owner else []
    feedback = await get_feedback(doc_id, user["id"]) if is_owner else None

    return templates.TemplateResponse(
        request,
        "document.html",
        {
            "user": user,
            "document": document,
            "recent_docs": recent_docs,
            "credits": usage.get("bonus_credits", 0) / 100,
            "is_admin": usage.get("is_admin", False),
            "enriched_contacts": enriched_contacts,
            "feedback": feedback,
            "is_owner": is_owner,
            "share_token": share_token,
            "app_url": settings.app_url,
            "org_slug": org_slug,
            "doc_slug": doc_slug,
            "linkedin_message_enabled": getattr(settings, "linkedin_message_enabled", False),
            "linkedin_connection_note_enabled": getattr(settings, "linkedin_connection_note_enabled", False),
        }
    )


@router.get("/@{org_slug}/{doc_slug}/og-image.png")
async def document_og_image_by_slug(org_slug: str, doc_slug: str):
    """Generate a dynamic OG image for a slug URL."""
    from services.og_image import generate_og_image

    meta = await get_document_meta_by_slug(org_slug, doc_slug)
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
async def document_og_image(doc_id: int, token: Optional[str] = None):
    """Generate a dynamic OG image for link previews (requires share token)."""
    from database import get_document_og_meta
    from services.og_image import generate_og_image

    meta = await get_document_og_meta(doc_id, share_token=token)
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
            product_context=get_effective_product_context(user),
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
    except SequenceValidationError as e:
        logger.warning("Outreach validation failed for doc %d: %s", doc_id, e.message,
                       extra={"event_type": "email_generation", "doc_id": doc_id, "error_code": e.code})
        return JSONResponse({
            "success": False,
            "error": {"code": e.code, "message": e.message},
        }, status_code=422)
    except Exception as e:
        logger.error("Error generating outreach for doc %d: %s", doc_id, e,
                     extra={"event_type": "email_generation", "doc_id": doc_id, "error_code": "outreach_generation_failed"})
        return JSONResponse({
            "success": False,
            "error": {"code": "outreach_generation_failed", "message": "Failed to generate outreach. Please try again."},
        }, status_code=500)


@router.post("/document/{doc_id}/linkedin-message")
async def generate_linkedin_message(
    doc_id: int,
    screenshot: UploadFile = File(None),
    mode: str = Form("dm"),
    user: dict = Depends(require_onboarding),
):
    """Generate a single LinkedIn message from a research document + optional screenshot."""
    # Feature flag gate
    if not getattr(settings, "linkedin_message_enabled", False):
        raise HTTPException(status_code=404, detail="Feature not enabled")

    # Connection note sub-flag
    if mode == "connection_request" and not getattr(settings, "linkedin_connection_note_enabled", False):
        logger.info("Connection note request blocked (flag off)", extra={"event_type": "linkedin_generation", "doc_id": doc_id, "error_code": "connection_note_disabled"})
        return JSONResponse({
            "success": False,
            "error": {"code": "connection_note_disabled", "message": "Connection notes are not enabled. Use DM mode instead."},
        }, status_code=422)

    # Validate mode
    if mode not in ("dm", "connection_request"):
        return JSONResponse({
            "success": False,
            "error": {"code": "invalid_mode", "message": "Mode must be 'dm' or 'connection_request'"},
        }, status_code=422)

    # Load document, validate ownership
    document = await get_document(doc_id, user_id=user["id"])
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    try:
        # Extract LinkedIn context from screenshot if provided
        if screenshot and screenshot.filename:
            try:
                image_bytes = await screenshot.read()
                if len(image_bytes) > 10 * 1024 * 1024:
                    return JSONResponse({
                        "success": False,
                        "error": {"code": "file_too_large", "message": "Screenshot must be under 10MB"},
                    }, status_code=422)

                if not (screenshot.content_type and screenshot.content_type.startswith("image/")):
                    return JSONResponse({
                        "success": False,
                        "error": {"code": "invalid_file", "message": "Please upload an image file"},
                    }, status_code=422)

                linkedin_context = await vision_service.extract_linkedin_context(
                    image_bytes, screenshot.content_type
                )

                if linkedin_context.get("content_type") == "other":
                    return JSONResponse({
                        "success": False,
                        "error": {
                            "code": "not_linkedin",
                            "message": "Screenshot does not appear to be from LinkedIn. Upload a LinkedIn profile or post screenshot, or use 'Generate from research only'.",
                        },
                    }, status_code=422)
            except Exception:
                logger.warning("Failed to extract LinkedIn context from screenshot", exc_info=True)
                linkedin_context = {"content_type": "none", "low_confidence": True}
        else:
            linkedin_context = {"content_type": "none", "low_confidence": True}

        # Build persona_context from linkedin_context if profile type
        persona_context = ""
        if linkedin_context.get("content_type") == "profile" and not linkedin_context.get("low_confidence"):
            persona_parts = []
            if linkedin_context.get("author_name"):
                persona_parts.append(f"**Name:** {linkedin_context['author_name']}")
            if linkedin_context.get("author_title"):
                persona_parts.append(f"**Title:** {linkedin_context['author_title']}")
            if linkedin_context.get("author_company"):
                persona_parts.append(f"**Company:** {linkedin_context['author_company']}")
            if persona_parts:
                persona_context = "\n".join(persona_parts)

        # Retrieve materials (non-fatal)
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

        result = await writing_service.generate_linkedin_message(
            document=document,
            product_context=get_effective_product_context(user),
            linkedin_context=linkedin_context,
            mode=mode,
            retrieved_materials=materials,
            seller_company=user.get("company_name", ""),
            problems_solved=user.get("problems_solved", ""),
            persona_context=persona_context,
            custom_signals=user.get("custom_signals", ""),
        )
        return JSONResponse({"success": True, **result})

    except SequenceValidationError as e:
        logger.warning("LinkedIn message validation failed for doc %d: %s", doc_id, e.message,
                       extra={"event_type": "linkedin_generation", "doc_id": doc_id, "error_code": e.code})
        return JSONResponse({
            "success": False,
            "error": {"code": e.code, "message": e.message},
        }, status_code=422)
    except Exception as e:
        logger.error("Error generating LinkedIn message for doc %d: %s", doc_id, e,
                     extra={"event_type": "linkedin_generation", "doc_id": doc_id, "error_code": "linkedin_generation_failed"})
        return JSONResponse({
            "success": False,
            "error": {"code": "linkedin_generation_failed", "message": "Failed to generate LinkedIn message. Please try again."},
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
        tech_by_domain = await tech_detection_service.analyze_multiple_domains(
            main_url=company_url,
            main_html=scraped_content.homepage_html
        )

        retrieved_materials = await collect_enrichment_data(
            scraped_content, company_url, user["id"],
        )

        document = await claude_service.generate_research_document(
            company_url=company_url,
            scraped=scraped_content,
            product_context=get_effective_product_context(user),
            tech_by_domain=tech_by_domain,
            retrieved_materials=retrieved_materials,
            seller_company=user.get("company_name", ""),
            target_personas=user.get("target_personas", ""),
            target_industries=user.get("target_industries", ""),
            problems_solved=user.get("problems_solved", ""),
            product_type=user.get("product_type", "saas"),
            custom_signals=user.get("custom_signals", ""),
            solution_motion=user.get("solution_motion", "horizontal"),
            seller_product_category=user.get("seller_product_category", ""),
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
