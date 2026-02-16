"""v1 API routes — authenticated via API key."""

import asyncio
import time
from datetime import datetime, timezone
from enum import Enum

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from api.auth import require_api_key
from api.errors import APIError
from api.idempotency import check_idempotency, save_idempotency
from database import (
    get_user_usage, get_document,
    save_enriched_contacts, get_enriched_contacts,
    get_research_job, list_user_jobs,
    use_credit, refund_credit, record_api_usage,
    create_bulk_job, get_bulk_job, list_bulk_jobs,
    create_bulk_job_items, get_bulk_job_items,
    create_list, get_list, list_lists as db_list_lists, delete_list, get_list_accounts,
    add_list_accounts, get_pending_list_accounts,
    update_list_status, update_list_credits,
    get_recent_document_by_url,
    try_start_list_analysis,
)
from api.validation import validate_company_url
from api.jobs import _run_research_pipeline
from api.tasks import create_tracked_task
from db.jobs import create_job_with_credit, create_research_job, count_user_jobs
from db.bulk import count_bulk_jobs
from db.lists import count_lists, count_list_accounts
from db.watchlist import count_watchlist_items
from api.ratelimit import research_limiter, sequence_limiter, default_limiter, bulk_limiter, clay_limiter


class SortField(str, Enum):
    composite_score = "composite_score"
    pain_score = "pain_score"
    fit_score = "fit_score"
    timing_score = "timing_score"
    created_at = "created_at"


class SortOrder(str, Enum):
    asc = "asc"
    desc = "desc"


CLAY_TIMEOUT = 120.0

router = APIRouter(prefix="/v1")


class ResearchRequest(BaseModel):
    company_url: str


class ScoreResponse(BaseModel):
    composite: int | None = None
    pain: int | None = None
    fit: int | None = None
    timing: int | None = None
    summary: str | None = None
    pain_evidence: list[str] | None = None
    pain_categories: dict[str, int] | None = None
    pain_signals: list[dict] | None = None


class ResearchResponse(BaseModel):
    success: bool
    document_id: int | None = None
    company_name: str | None = None
    company_url: str | None = None
    scores: ScoreResponse | None = None
    sections: dict | None = None
    error: str | None = None


def _parse_evidence(pain_evidence: str | None) -> list[str]:
    """Parse bullet-point pain_evidence text into a list of strings."""
    if not pain_evidence:
        return []
    lines = []
    for line in pain_evidence.strip().splitlines():
        cleaned = line.strip().lstrip("-•*").strip()
        if cleaned:
            lines.append(cleaned)
    return lines


def synthesize_pain(inferences: list[dict], pain_evidence: str | None) -> dict:
    """Build pain_categories + pain_signals from stored inferences."""
    categories: dict[str, int] = {}
    signals: list[dict] = []

    for inf in inferences:
        cat = inf.get("category", "engineering")
        conf = inf.get("confidence", 0)
        # Max confidence per category
        if cat not in categories or conf > categories[cat]:
            categories[cat] = conf
        signals.append({
            "title": inf["title"],
            "severity": inf["severity"],
            "confidence": conf,
            "category": cat,
        })

    evidence_list = _parse_evidence(pain_evidence)
    summary = evidence_list[0] if evidence_list else None

    return {
        "categories": categories or None,
        "signals": signals or None,
        "evidence": evidence_list or None,
        "summary": summary,
    }


@router.get("/ping", tags=["Account"])
async def ping(api_user: dict = Depends(require_api_key)):
    """Health check endpoint. Returns 200 if API key is valid."""
    default_limiter.check(api_user["api_key_id"])
    return {"status": "ok", "user_id": api_user["id"]}


@router.get("/account", tags=["Account"])
async def get_account(api_user: dict = Depends(require_api_key)):
    """Get account info: credits, subscription, org, and API key usage."""
    from database import get_user_by_id
    from db.api_keys import list_api_keys, get_api_key_usage_stats

    default_limiter.check(api_user["api_key_id"])

    user = await get_user_by_id(api_user["id"])
    if not user:
        raise APIError("not_found", "User not found", 404)

    usage = await get_user_usage(api_user["id"])
    keys = await list_api_keys(api_user["id"])
    key_stats = await get_api_key_usage_stats(api_user["id"])

    return {
        "user_id": user["id"],
        "email": user.get("email"),
        "organization": {
            "name": user.get("org_name"),
            "slug": user.get("org_slug"),
        },
        "credits": {
            "balance": usage.get("bonus_credits", 0) // 100,
            "unit": "credits",
        },
        "subscription": {
            "status": usage.get("subscription_status", "none"),
            "billing_period_start": (
                usage["billing_period_start"].isoformat()
                if usage.get("billing_period_start")
                else None
            ),
        },
        "api_keys": [
            {
                "id": k["id"],
                "prefix": k["prefix"],
                "name": k["name"],
                "created_at": k["created_at"].isoformat(),
                "last_used_at": k["last_used_at"].isoformat() if k.get("last_used_at") else None,
                "usage": key_stats.get(k["id"], {"requests": 0, "credits": 0}),
            }
            for k in keys
        ],
    }


@router.post("/research", status_code=202, tags=["Research"])
async def create_research(request: Request, body: ResearchRequest, api_user: dict = Depends(require_api_key)):
    """Start an async research job. Returns immediately with a job_id."""
    research_limiter.check(api_user["api_key_id"])

    idem_key, cached = await check_idempotency(request, api_user["api_key_id"])
    if cached:
        return cached

    try:
        company_url = validate_company_url(body.company_url)
    except ValueError as e:
        raise APIError("validation_error", str(e), 422)

    # 24h cache: return existing document instead of re-running pipeline
    cached_doc_id = await get_recent_document_by_url(api_user["id"], company_url)
    if cached_doc_id:
        response_body = {"job_id": None, "status": "completed", "document_id": cached_doc_id, "cached": True}
        if idem_key:
            await save_idempotency(api_user["api_key_id"], idem_key, 202, response_body)
        return response_body

    # Atomically reserve credit + create job
    usage = await get_user_usage(api_user["id"])
    is_admin = usage.get("is_admin", False)
    if not is_admin:
        try:
            job = await create_job_with_credit(api_user["id"], api_user["api_key_id"], company_url)
        except ValueError:
            raise APIError("insufficient_credits", "No credits remaining", 402)
    else:
        job = await create_research_job(api_user["id"], api_user["api_key_id"], company_url)

    await create_tracked_task(
        "research",
        {"job_id": job["id"], "user_id": api_user["id"], "api_key_id": api_user["api_key_id"], "company_url": company_url, "is_admin": is_admin},
        name=f"research-{job['id']}",
    )

    response_body = {"job_id": job["id"], "status": "processing"}
    if idem_key:
        await save_idempotency(api_user["api_key_id"], idem_key, 202, response_body)
    return response_body


@router.get("/research/{job_id}", tags=["Research"])
async def get_job_status(job_id: int, api_user: dict = Depends(require_api_key)):
    """Poll for job status. Returns full result when completed."""
    default_limiter.check(api_user["api_key_id"])
    job = await get_research_job(job_id, api_user["id"])
    if not job:
        raise APIError("not_found", "Job not found", 404)

    # Read-path timeout: if processing for >10 minutes, mark as failed and refund
    if job["status"] == "processing" and job["created_at"]:
        created = job["created_at"]
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age_seconds = (datetime.now(timezone.utc) - created).total_seconds()
        if age_seconds > 600:  # 10 minutes
            from database import update_job_status
            await update_job_status(job_id, "failed", error_message="Job timed out after 10 minutes")
            usage = await get_user_usage(api_user["id"])
            if not usage.get("is_admin", False):
                await refund_credit(api_user["id"])
            job = await get_research_job(job_id, api_user["id"])

    result = {
        "job_id": job["id"],
        "status": job["status"],
        "progress": job.get("progress"),
        "company_url": job["company_url"],
        "created_at": job["created_at"].isoformat(),
        "completed_at": job["completed_at"].isoformat() if job["completed_at"] else None,
    }

    if job["status"] == "failed":
        result["error"] = job["error_message"]

    if job["status"] == "completed" and job["document_id"]:
        doc = await get_document(job["document_id"], api_user["id"])
        if doc:
            from db.tech_signals import get_pain_inferences
            inferences = await get_pain_inferences(job["document_id"])
            pain = synthesize_pain(inferences, doc.pain_evidence)

            result["document_id"] = job["document_id"]
            result["company_name"] = doc.company_name
            result["scores"] = {
                "composite": doc.opportunity_score,
                "pain": doc.pain_score,
                "fit": doc.fit_score,
                "timing": doc.timing_score,
                "summary": doc.score_summary,
                "pain_evidence": pain["evidence"],
                "pain_categories": pain["categories"],
                "pain_signals": pain["signals"],
            }
            result["sections"] = {
                "company_overview": doc.company_overview,
                "projects_initiatives": doc.projects_initiatives,
                "confirmed_tech_stack": doc.confirmed_tech_stack,
                "hiring_signals": doc.hiring_signals,
                "business_problems": doc.business_problems,
                "existential_data_points": doc.existential_data_points,
                "before_scenario": doc.before_scenario,
                "pvp_seed": doc.pvp_seed,
                "required_capabilities": doc.required_capabilities,
                "product_fit": doc.product_fit,
                "talking_points": doc.talking_points,
                "recent_news": doc.recent_news,
                "key_contacts": doc.key_contacts,
                "recommended_contacts": doc.recommended_contacts,
                "information_gaps": doc.information_gaps,
            }

    return result


@router.get("/research", tags=["Research"])
async def list_jobs(
    api_user: dict = Depends(require_api_key),
    limit: int = Query(100, ge=1, le=500, description="Max results to return"),
    offset: int = Query(0, ge=0, description="Number of results to skip"),
):
    """List the user's recent research jobs."""
    default_limiter.check(api_user["api_key_id"])
    jobs, total = await asyncio.gather(
        list_user_jobs(api_user["id"], limit=limit, offset=offset),
        count_user_jobs(api_user["id"]),
    )
    return {
        "jobs": [
            {
                "job_id": j["id"],
                "company_url": j["company_url"],
                "status": j["status"],
                "document_id": j["document_id"],
                "error": j["error_message"],
                "created_at": j["created_at"].isoformat(),
                "completed_at": j["completed_at"].isoformat() if j["completed_at"] else None,
            }
            for j in jobs
        ],
        "total": total,
        "has_more": (offset + limit) < total,
    }


class EnrichRequest(BaseModel):
    document_id: int
    titles: list[str] | None = None  # Optional custom titles; defaults to user's ICP


class EnrichContact(BaseModel):
    name: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    title: str | None = None
    email: str | None = None
    email_status: str | None = None
    profile_url: str | None = None
    company_name: str | None = None


class EnrichResponse(BaseModel):
    success: bool
    contacts: list[EnrichContact] = []
    cached: bool = False
    error: str | None = None


@router.post("/enrich", response_model=EnrichResponse, tags=["Research"])
async def enrich_contacts(request: Request, body: EnrichRequest, api_user: dict = Depends(require_api_key)):
    """Enrich contacts for an existing research document using LeadMagic."""
    research_limiter.check(api_user["api_key_id"])

    idem_key, cached = await check_idempotency(request, api_user["api_key_id"])
    if cached:
        return cached

    from services.leadmagic import LeadMagicService
    leadmagic = LeadMagicService()

    if not leadmagic.is_configured():
        raise APIError("validation_error", "Contact enrichment is not yet configured.", 422)

    document = await get_document(body.document_id, user_id=api_user["id"])
    if not document:
        raise APIError("not_found", "Document not found", 404)

    # Check if already enriched
    existing = await get_enriched_contacts(body.document_id, api_user["id"])
    if existing:
        return EnrichResponse(
            success=True,
            contacts=[EnrichContact(**{k: v for k, v in c.items() if k in EnrichContact.model_fields}) for c in existing],
            cached=True,
        )

    # Check credits (enrichment = 50 cents = 0.5 credits)
    usage = await get_user_usage(api_user["id"])
    is_admin = usage.get("is_admin", False)
    if not is_admin and usage.get("bonus_credits", 0) < 50:
        raise APIError("insufficient_credits", "Insufficient credits (enrichment costs 0.5 credits)", 402)

    # Use custom titles or fall back to user's ICP
    titles = body.titles
    if not titles:
        titles = _build_default_titles(api_user)

    company_domain = document.company_url.replace("https://", "").replace("http://", "").split("/")[0].replace("www.", "")

    try:
        contacts = await leadmagic.enrich_contacts(
            company_domain=company_domain,
            company_name=document.company_name,
            target_titles=titles,
        )

        if contacts:
            await save_enriched_contacts(body.document_id, api_user["id"], contacts)
            if not is_admin:
                await use_credit(api_user["id"], cents=50)

        await record_api_usage(api_user["api_key_id"], "/v1/enrich", 1)

        response_body = EnrichResponse(
            success=True,
            contacts=[EnrichContact(**c) for c in contacts],
            cached=False,
        )
        if idem_key:
            await save_idempotency(api_user["api_key_id"], idem_key, 200, response_body.model_dump())
        return response_body
    except Exception as e:
        raise APIError("internal_error", str(e)[:500], 500)



# =============================================================================
# Clay Sync Enrichment
# =============================================================================

class ClayEnrichRequest(BaseModel):
    company_url: str


def _truncate(text: str | None, max_len: int = 500) -> str:
    """Truncate text to max_len characters."""
    if not text:
        return ""
    return text[:max_len] + ("..." if len(text) > max_len else "")


def _build_clay_response(doc, *, cached: bool, duration: float | None = None, error: str | None = None, pain_synthesis: dict | None = None) -> dict:
    """Build flat Clay-friendly response from a ResearchDocument."""
    cats = (pain_synthesis or {}).get("categories") or {}
    signals = (pain_synthesis or {}).get("signals") or []
    top_signal = signals[0]["title"] if signals else None
    pain_reasons = _truncate(doc.pain_evidence or doc.business_problems)

    resp = {
        "success": True,
        "company_name": doc.company_name,
        "company_url": doc.company_url,
        "pain_score": doc.pain_score,
        "fit_score": doc.fit_score,
        "timing_score": doc.timing_score,
        "composite_score": doc.opportunity_score,
        "score_summary": _truncate(doc.score_summary),
        "pain_reasons": pain_reasons,
        "business_problems": _truncate(doc.business_problems),
        "product_fit": _truncate(doc.product_fit),
        "talking_points": _truncate(doc.talking_points),
        "existential_data_points": _truncate(doc.existential_data_points),
        "pvp_seed": _truncate(doc.pvp_seed),
        "required_capabilities": _truncate(doc.required_capabilities),
        "pain_category_security": cats.get("security"),
        "pain_category_engineering": cats.get("engineering"),
        "pain_category_operations": cats.get("operations"),
        "pain_category_marketing": cats.get("marketing"),
        "pain_category_data": cats.get("data"),
        "top_pain_signal": top_signal,
        "document_id": doc.id,
        "cached": cached,
        "research_duration_seconds": round(duration, 2) if duration is not None else None,
        "error": error,
    }
    return resp


@router.post("/clay/enrich", tags=["Research"])
async def clay_enrich(request: Request, body: ClayEnrichRequest, api_user: dict = Depends(require_api_key)):
    """Synchronous enrichment endpoint optimized for Clay HTTP columns.

    Runs the full research pipeline and returns a flat JSON response.
    Uses 24-hour caching to avoid duplicate costs.
    """
    clay_limiter.check(api_user["api_key_id"])

    idem_key, cached = await check_idempotency(request, api_user["api_key_id"])
    if cached:
        return cached

    # Validate URL
    try:
        company_url = validate_company_url(body.company_url)
    except ValueError as e:
        raise APIError("validation_error", str(e), 422)

    # Check 24h cache
    cached_doc_id = await get_recent_document_by_url(api_user["id"], company_url)
    if cached_doc_id:
        cached_doc = await get_document(cached_doc_id, api_user["id"])
        if cached_doc:
            await record_api_usage(api_user["api_key_id"], "/v1/clay/enrich", 0)
            from db.tech_signals import get_pain_inferences
            inferences = await get_pain_inferences(cached_doc.id)
            pain = synthesize_pain(inferences, cached_doc.pain_evidence)
            response_body = _build_clay_response(cached_doc, cached=True, pain_synthesis=pain)
            if idem_key:
                await save_idempotency(api_user["api_key_id"], idem_key, 200, response_body)
            return response_body

    # Atomically reserve credit + create job
    usage = await get_user_usage(api_user["id"])
    is_admin = usage.get("is_admin", False)
    if not is_admin:
        try:
            job = await create_job_with_credit(api_user["id"], api_user["api_key_id"], company_url)
        except ValueError:
            raise APIError("insufficient_credits", "No credits remaining", 402)
    else:
        job = await create_research_job(api_user["id"], api_user["api_key_id"], company_url)

    # Run pipeline synchronously with 120s timeout
    start = time.monotonic()
    try:
        doc_id = await asyncio.wait_for(
            _run_research_pipeline(api_user["id"], company_url),
            timeout=CLAY_TIMEOUT,
        )
        duration = time.monotonic() - start

        await record_api_usage(api_user["api_key_id"], "/v1/clay/enrich", 1)
        from database import update_job_status
        await update_job_status(job["id"], "completed", document_id=doc_id)

        doc = await get_document(doc_id, api_user["id"])
        from db.tech_signals import get_pain_inferences
        inferences = await get_pain_inferences(doc_id)
        pain = synthesize_pain(inferences, doc.pain_evidence)
        response_body = _build_clay_response(doc, cached=False, duration=duration, pain_synthesis=pain)
        if idem_key:
            await save_idempotency(api_user["api_key_id"], idem_key, 200, response_body)
        return response_body

    except asyncio.TimeoutError:
        if not is_admin:
            await refund_credit(api_user["id"])
        from database import update_job_status
        await update_job_status(job["id"], "failed", error_message="Research timed out after 120 seconds")
        raise APIError("timeout", "Research timed out after 120 seconds", 504)

    except Exception as e:
        duration = time.monotonic() - start
        if not is_admin:
            await refund_credit(api_user["id"])
        from database import update_job_status
        await update_job_status(job["id"], "failed", error_message=str(e)[:500])
        raise APIError("internal_error", str(e)[:500], 500)


def _build_default_titles(user: dict) -> list[str]:
    """Build target titles from user ICP or use sensible defaults."""
    # Simple defaults — the UI version in main.py has the full ICP mapping
    return ["CTO", "VP Engineering", "VP Sales", "CEO", "Director of Engineering"][:5]


# =============================================================================
# Sequence Generation
# =============================================================================

class SequenceEmail(BaseModel):
    email_number: int
    subject: str
    body: str


class SequenceResponse(BaseModel):
    success: bool
    document_id: int
    emails: list[SequenceEmail] = []
    error: str | None = None


@router.post("/research/{doc_id}/sequence", response_model=SequenceResponse, tags=["Sequences"])
async def generate_sequence(doc_id: int, api_user: dict = Depends(require_api_key)):
    """Generate a 3-email outreach sequence from a completed research document."""
    sequence_limiter.check(api_user["api_key_id"])

    document = await get_document(doc_id, user_id=api_user["id"])
    if not document:
        raise APIError("not_found", "Document not found", 404)

    from services.instances import writing_service

    try:
        # Retrieve relevant materials (non-fatal if unavailable)
        materials = ""
        try:
            from services.collect import _get_retrieval_service
            retrieval = _get_retrieval_service()
            if retrieval:
                materials = await retrieval.get_relevant_context(
                    user_id=api_user["id"],
                    company_name=document.company_name,
                    company_description=document.company_overview[:500] if document.company_overview else "",
                ) or ""
        except Exception:
            pass

        emails, subject_options = await writing_service.generate_email_sequence(
            document=document,
            product_context=api_user.get("product_context", ""),
            product_type=api_user.get("product_type", "saas"),
            retrieved_materials=materials,
            seller_company=api_user.get("company_name", ""),
            problems_solved=api_user.get("problems_solved", ""),
            custom_signals=api_user.get("custom_signals", ""),
        )

        await record_api_usage(api_user["api_key_id"], "/v1/research/sequence", 0)

        return SequenceResponse(
            success=True,
            document_id=doc_id,
            emails=[SequenceEmail(**e) for e in emails],
        )
    except Exception as e:
        raise APIError("internal_error", str(e)[:500], 500)


# =============================================================================
# Bulk Research
# =============================================================================

class BulkResearchRequest(BaseModel):
    company_urls: list[str]
    name: str | None = None


@router.post("/research/bulk", status_code=202, tags=["Bulk"])
async def create_bulk_research(request: Request, body: BulkResearchRequest, api_user: dict = Depends(require_api_key)):
    """Start a bulk research job. Accepts up to 100 URLs."""
    bulk_limiter.check(api_user["api_key_id"])

    idem_key, cached = await check_idempotency(request, api_user["api_key_id"])
    if cached:
        return cached

    if not body.company_urls:
        raise APIError("validation_error", "company_urls must not be empty", 422)
    if len(body.company_urls) > 100:
        raise APIError("validation_error", "Maximum 100 URLs per bulk job", 422)

    # Validate all URLs upfront
    validated_urls = []
    for url in body.company_urls:
        try:
            validated_urls.append(validate_company_url(url))
        except ValueError as e:
            raise APIError("validation_error", f"Invalid URL '{url}': {e}", 422)

    # Reserve credits upfront atomically
    n = len(validated_urls)
    usage = await get_user_usage(api_user["id"])
    is_admin = usage.get("is_admin", False)
    if not is_admin:
        credits_needed = n * 100  # cents
        ok = await use_credit(api_user["id"], cents=credits_needed)
        if not ok:
            raise APIError("insufficient_credits", f"Insufficient credits. Need {n}, have {usage.get('bonus_credits', 0) // 100}", 402)

    bulk_job = await create_bulk_job(api_user["id"], api_user["api_key_id"], body.name, n, n * 100)
    await create_bulk_job_items(bulk_job["id"], validated_urls)

    await create_tracked_task(
        "bulk",
        {"bulk_job_id": bulk_job["id"], "user_id": api_user["id"], "api_key_id": api_user["api_key_id"], "is_admin": is_admin},
        name=f"bulk-{bulk_job['id']}",
    )

    response_body = {"bulk_job_id": bulk_job["id"], "status": "processing", "total_items": n}
    if idem_key:
        await save_idempotency(api_user["api_key_id"], idem_key, 202, response_body)
    return response_body


@router.get("/research/bulk/{bulk_job_id}", tags=["Bulk"])
async def get_bulk_job_status(bulk_job_id: int, api_user: dict = Depends(require_api_key)):
    """Get bulk job progress and all items."""
    default_limiter.check(api_user["api_key_id"])
    job = await get_bulk_job(bulk_job_id, api_user["id"])
    if not job:
        raise APIError("not_found", "Bulk job not found", 404)

    items = await get_bulk_job_items(bulk_job_id)

    # Timeout check: mark stale processing items as failed
    from database import update_bulk_job_item
    now = datetime.now(timezone.utc)
    for item in items:
        if item["status"] == "processing" and item["created_at"]:
            created = item["created_at"]
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if (now - created).total_seconds() > 600:
                await update_bulk_job_item(item["id"], "failed", error_message="Item timed out after 10 minutes")
                item["status"] = "failed"
                item["error_message"] = "Item timed out after 10 minutes"

    return {
        "bulk_job_id": job["id"],
        "name": job["name"],
        "status": job["status"],
        "total_items": job["total_items"],
        "completed_items": job["completed_items"],
        "failed_items": job["failed_items"],
        "credits_reserved": job["credits_reserved"],
        "created_at": job["created_at"].isoformat(),
        "completed_at": job["completed_at"].isoformat() if job["completed_at"] else None,
        "items": [
            {
                "id": item["id"],
                "company_url": item["company_url"],
                "status": item["status"],
                "research_job_id": item["research_job_id"],
                "document_id": item["document_id"],
                "error": item["error_message"],
                "created_at": item["created_at"].isoformat(),
                "completed_at": item["completed_at"].isoformat() if item["completed_at"] else None,
            }
            for item in items
        ],
    }


@router.get("/research/bulk", tags=["Bulk"])
async def list_bulk_jobs_endpoint(
    api_user: dict = Depends(require_api_key),
    limit: int = Query(100, ge=1, le=500, description="Max results to return"),
    offset: int = Query(0, ge=0, description="Number of results to skip"),
):
    """List recent bulk jobs (summaries only)."""
    default_limiter.check(api_user["api_key_id"])
    jobs, total = await asyncio.gather(
        list_bulk_jobs(api_user["id"], limit=limit, offset=offset),
        count_bulk_jobs(api_user["id"]),
    )
    return {
        "bulk_jobs": [
            {
                "bulk_job_id": j["id"],
                "name": j["name"],
                "status": j["status"],
                "total_items": j["total_items"],
                "completed_items": j["completed_items"],
                "failed_items": j["failed_items"],
                "created_at": j["created_at"].isoformat(),
                "completed_at": j["completed_at"].isoformat() if j["completed_at"] else None,
            }
            for j in jobs
        ],
        "total": total,
        "has_more": (offset + limit) < total,
    }


# =============================================================================
# Lists
# =============================================================================

class CreateListRequest(BaseModel):
    name: str
    company_urls: list[str]
    analyze: bool = False


@router.post("/lists", status_code=201, tags=["Lists"])
async def create_list_endpoint(request: Request, body: CreateListRequest, api_user: dict = Depends(require_api_key)):
    """Create a persistent list of companies. Optionally trigger analysis immediately."""
    bulk_limiter.check(api_user["api_key_id"])

    idem_key, cached = await check_idempotency(request, api_user["api_key_id"])
    if cached:
        return cached

    if not body.company_urls:
        raise APIError("validation_error", "company_urls must not be empty", 422)
    if len(body.company_urls) > 100:
        raise APIError("validation_error", "Maximum 100 URLs per list", 422)
    if not body.name or not body.name.strip():
        raise APIError("validation_error", "name is required", 422)

    # Validate and deduplicate URLs upfront
    validated_urls = []
    seen = set()
    for url in body.company_urls:
        try:
            v = validate_company_url(url)
        except ValueError as e:
            raise APIError("validation_error", f"Invalid URL '{url}': {e}", 422)
        if v not in seen:
            seen.add(v)
            validated_urls.append(v)

    n = len(validated_urls)
    usage = await get_user_usage(api_user["id"])
    is_admin = usage.get("is_admin", False)

    # Reserve credits atomically if analyzing immediately
    if body.analyze and not is_admin:
        credits_needed = n * 100
        ok = await use_credit(api_user["id"], cents=credits_needed)
        if not ok:
            raise APIError("insufficient_credits", f"Insufficient credits. Need {n}, have {usage.get('bonus_credits', 0) // 100}", 402)

    lst = await create_list(api_user["id"], api_user["api_key_id"], body.name.strip(), org_id=api_user.get("org_id"))
    await add_list_accounts(lst["id"], validated_urls)

    if body.analyze:
        await update_list_credits(lst["id"], n * 100)
        await update_list_status(lst["id"], "analyzing")
        await create_tracked_task(
            "list_analysis",
            {"list_id": lst["id"], "user_id": api_user["id"], "api_key_id": api_user["api_key_id"], "is_admin": is_admin},
            name=f"list-{lst['id']}",
        )
        status = "analyzing"
    else:
        status = "created"

    response_body = {
        "list_id": lst["id"],
        "name": lst["name"],
        "status": status,
        "total_accounts": n,
    }
    if idem_key:
        await save_idempotency(api_user["api_key_id"], idem_key, 201, response_body)
    return response_body


@router.post("/lists/{list_id}/analyze", status_code=202, tags=["Lists"])
async def analyze_list_endpoint(request: Request, list_id: int, api_user: dict = Depends(require_api_key)):
    """Trigger analysis on a list's pending accounts."""
    bulk_limiter.check(api_user["api_key_id"])

    idem_key, cached = await check_idempotency(request, api_user["api_key_id"])
    if cached:
        return cached

    lst = await get_list(list_id, api_user["id"])
    if not lst:
        raise APIError("not_found", "List not found", 404)

    # Atomic status transition — prevents concurrent analysis starts
    started = await try_start_list_analysis(list_id)
    if not started:
        raise APIError("conflict", "List is already being analyzed", 409)

    pending = await get_pending_list_accounts(list_id)
    if not pending:
        raise APIError("validation_error", "No pending accounts to analyze", 422)

    n = len(pending)
    usage = await get_user_usage(api_user["id"])
    is_admin = usage.get("is_admin", False)

    if not is_admin:
        credits_needed = n * 100
        ok = await use_credit(api_user["id"], cents=credits_needed)
        if not ok:
            raise APIError("insufficient_credits", f"Insufficient credits. Need {n}, have {usage.get('bonus_credits', 0) // 100}", 402)

    await update_list_credits(list_id, (lst["credits_reserved"] or 0) + n * 100)
    await create_tracked_task(
        "list_analysis",
        {"list_id": list_id, "user_id": api_user["id"], "api_key_id": api_user["api_key_id"], "is_admin": is_admin},
        name=f"list-analyze-{list_id}",
    )

    response_body = {"list_id": list_id, "status": "analyzing", "pending_accounts": n}
    if idem_key:
        await save_idempotency(api_user["api_key_id"], idem_key, 202, response_body)
    return response_body


@router.get("/lists/{list_id}", tags=["Lists"])
async def get_list_endpoint(
    list_id: int,
    api_user: dict = Depends(require_api_key),
    min_pain_score: int | None = Query(None, ge=0, le=100, description="Minimum pain score filter (0-100)"),
    min_composite_score: int | None = Query(None, ge=0, le=100, description="Minimum composite score filter (0-100)"),
    sort_by: SortField = Query(SortField.composite_score, description="Field to sort results by"),
    order: SortOrder = Query(SortOrder.desc, description="Sort direction"),
    limit: int = Query(100, ge=1, le=500, description="Max results to return"),
    offset: int = Query(0, ge=0, description="Number of results to skip"),
):
    """Get list details with accounts, optional filtering/sorting."""
    default_limiter.check(api_user["api_key_id"])

    lst = await get_list(list_id, api_user["id"])
    if not lst:
        raise APIError("not_found", "List not found", 404)

    accounts, total = await asyncio.gather(
        get_list_accounts(
            list_id,
            min_pain=min_pain_score,
            min_composite=min_composite_score,
            sort_by=sort_by.value,
            order=order.value,
            limit=limit,
            offset=offset,
        ),
        count_list_accounts(list_id, min_pain=min_pain_score, min_composite=min_composite_score),
    )

    return {
        "list_id": lst["id"],
        "name": lst["name"],
        "status": lst["status"],
        "total_accounts": lst["total_accounts"],
        "analyzed_accounts": lst["analyzed_accounts"],
        "failed_accounts": lst["failed_accounts"],
        "accounts": [
            {
                "id": a["id"],
                "company_url": a["company_url"],
                "company_name": a["company_name"],
                "status": a["status"],
                "document_id": a["document_id"],
                "pain_score": a["pain_score"],
                "fit_score": a["fit_score"],
                "timing_score": a["timing_score"],
                "composite_score": a["composite_score"],
                "analyzed_at": a["analyzed_at"].isoformat() if a["analyzed_at"] else None,
            }
            for a in accounts
        ],
        "total": total,
        "has_more": (offset + limit) < total,
    }


@router.get("/lists", tags=["Lists"])
async def list_lists_endpoint(
    api_user: dict = Depends(require_api_key),
    limit: int = Query(100, ge=1, le=500, description="Max results to return"),
    offset: int = Query(0, ge=0, description="Number of results to skip"),
):
    """List user's recent lists (summaries, no accounts)."""
    default_limiter.check(api_user["api_key_id"])
    lists, total = await asyncio.gather(
        db_list_lists(api_user["id"], limit=limit, offset=offset),
        count_lists(api_user["id"]),
    )
    return {
        "lists": [
            {
                "list_id": l["id"],
                "name": l["name"],
                "status": l["status"],
                "total_accounts": l["total_accounts"],
                "analyzed_accounts": l["analyzed_accounts"],
                "failed_accounts": l["failed_accounts"],
                "created_at": l["created_at"].isoformat(),
                "updated_at": l["updated_at"].isoformat() if l["updated_at"] else None,
            }
            for l in lists
        ],
        "total": total,
        "has_more": (offset + limit) < total,
    }


@router.delete("/lists/{list_id}", status_code=204, tags=["Lists"])
async def delete_list_endpoint(list_id: int, api_user: dict = Depends(require_api_key)):
    """Delete a list and all its accounts."""
    default_limiter.check(api_user["api_key_id"])
    deleted = await delete_list(list_id, api_user["id"])
    if not deleted:
        raise APIError("not_found", "List not found", 404)
    return JSONResponse(status_code=204, content=None)


class PushInstantlyRequest(BaseModel):
    campaign_id: str
    account_ids: list[int] | None = None


@router.post("/lists/{list_id}/push", tags=["Lists"])
async def push_list_to_instantly(list_id: int, body: PushInstantlyRequest, api_user: dict = Depends(require_api_key)):
    """Push accounts from a list to an Instantly campaign via API."""
    from database import get_integration, get_enriched_contacts as get_contacts
    from services.instantly import push_accounts_to_instantly

    default_limiter.check(api_user["api_key_id"])

    lst = await get_list(list_id, api_user["id"])
    if not lst:
        raise APIError("not_found", "List not found", 404)

    integration = await get_integration(api_user["id"], "instantly")
    if not integration:
        raise APIError("validation_error", "Instantly not connected", 400)

    all_accounts = await get_list_accounts(list_id)
    if body.account_ids:
        accounts = [a for a in all_accounts if a["id"] in body.account_ids]
    else:
        accounts = [a for a in all_accounts if a.get("status") == "completed"]

    if not accounts:
        raise APIError("validation_error", "No accounts to push", 400)

    contacts_by_account = {}
    for account in accounts:
        if account.get("document_id"):
            contacts = await get_contacts(account["document_id"])
            if contacts:
                contacts_by_account[account["id"]] = contacts

    result = await push_accounts_to_instantly(
        api_user["id"], body.campaign_id, accounts, contacts_by_account,
    )
    return result


# =================================================================
# Team API Routes
# =================================================================

class InviteRequest(BaseModel):
    email: str
    role: str = "member"


class RoleUpdate(BaseModel):
    role: str


@router.get("/team", tags=["Team"])
async def api_list_team(api_user: dict = Depends(require_api_key)):
    """List team members."""
    from database import get_org_members, get_user_by_id
    user = await get_user_by_id(api_user["id"])
    if not user or not user.get("org_id"):
        raise APIError("validation_error", "No organization found", 400)
    members = await get_org_members(user["org_id"])
    return {"members": members}


@router.post("/team/invite", tags=["Team"])
async def api_invite_member(body: InviteRequest, api_user: dict = Depends(require_api_key)):
    """Invite a team member (admin only)."""
    from database import get_user_by_id, create_org_invite
    user = await get_user_by_id(api_user["id"])
    if not user or user.get("org_role") != "admin":
        raise APIError("forbidden", "Admin access required", 403)
    if body.role not in ("admin", "member", "viewer"):
        raise APIError("validation_error", "Invalid role", 400)
    invite = await create_org_invite(user["org_id"], body.email, body.role, user["id"])
    return {"invite": {"id": invite["id"], "email": invite["email"], "role": invite["role"], "token": invite["token"], "expires_at": str(invite["expires_at"])}}


@router.delete("/team/members/{member_id}", tags=["Team"])
async def api_remove_member(member_id: int, api_user: dict = Depends(require_api_key)):
    """Remove a team member (admin only)."""
    from database import get_user_by_id, remove_org_member
    user = await get_user_by_id(api_user["id"])
    if not user or user.get("org_role") != "admin":
        raise APIError("forbidden", "Admin access required", 403)
    if member_id == user["id"]:
        raise APIError("validation_error", "Cannot remove yourself", 400)
    removed = await remove_org_member(user["org_id"], member_id)
    if not removed:
        raise APIError("not_found", "Member not found", 404)
    return {"removed": True}


@router.patch("/team/members/{member_id}", tags=["Team"])
async def api_change_role(member_id: int, body: RoleUpdate, api_user: dict = Depends(require_api_key)):
    """Change a team member's role (admin only)."""
    from database import get_user_by_id, update_member_role
    user = await get_user_by_id(api_user["id"])
    if not user or user.get("org_role") != "admin":
        raise APIError("forbidden", "Admin access required", 403)
    if member_id == user["id"]:
        raise APIError("validation_error", "Cannot change your own role", 400)
    if body.role not in ("admin", "member", "viewer"):
        raise APIError("validation_error", "Invalid role", 400)
    updated = await update_member_role(user["org_id"], member_id, body.role)
    if not updated:
        raise APIError("not_found", "Member not found", 404)
    return {"updated": True}


# =================================================================
# Watchlist API Routes
# =================================================================

class WatchlistAddRequest(BaseModel):
    company_url: str
    company_name: str | None = None
    schedule: str = "biweekly"


class WatchlistUpdateRequest(BaseModel):
    schedule: str | None = None
    status: str | None = None


@router.post("/watchlist", status_code=201, tags=["Watchlist"])
async def add_to_watchlist(body: WatchlistAddRequest, api_user: dict = Depends(require_api_key)):
    """Add a company URL to the watchlist with a recurring schedule."""
    default_limiter.check(api_user["api_key_id"])

    if body.schedule not in ("weekly", "biweekly", "monthly"):
        raise APIError("validation_error", "schedule must be weekly, biweekly, or monthly", 422)

    try:
        company_url = validate_company_url(body.company_url)
    except ValueError as e:
        raise APIError("validation_error", str(e), 422)

    from database import create_watchlist_item
    item = await create_watchlist_item(
        api_user["id"], company_url, body.company_name, body.schedule,
    )
    return {
        "id": item["id"],
        "company_url": item["company_url"],
        "company_name": item["company_name"],
        "schedule": item["schedule"],
        "status": item["status"],
        "next_run_at": item["next_run_at"].isoformat(),
    }


@router.get("/watchlist", tags=["Watchlist"])
async def list_watchlist(
    api_user: dict = Depends(require_api_key),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List all watched companies."""
    default_limiter.check(api_user["api_key_id"])
    from database import list_watchlist_items
    items, total = await asyncio.gather(
        list_watchlist_items(api_user["id"], limit=limit, offset=offset),
        count_watchlist_items(api_user["id"]),
    )
    return {
        "items": [
            {
                "id": i["id"],
                "company_url": i["company_url"],
                "company_name": i["company_name"],
                "schedule": i["schedule"],
                "status": i["status"],
                "last_document_id": i["last_document_id"],
                "last_run_at": i["last_run_at"].isoformat() if i["last_run_at"] else None,
                "next_run_at": i["next_run_at"].isoformat(),
                "created_at": i["created_at"].isoformat(),
            }
            for i in items
        ],
        "total": total,
        "has_more": (offset + limit) < total,
    }


@router.patch("/watchlist/{item_id}", tags=["Watchlist"])
async def update_watchlist(item_id: int, body: WatchlistUpdateRequest, api_user: dict = Depends(require_api_key)):
    """Update schedule or pause/resume a watchlist item."""
    default_limiter.check(api_user["api_key_id"])

    if body.schedule and body.schedule not in ("weekly", "biweekly", "monthly"):
        raise APIError("validation_error", "schedule must be weekly, biweekly, or monthly", 422)
    if body.status and body.status not in ("active", "paused"):
        raise APIError("validation_error", "status must be active or paused", 422)

    from database import update_watchlist_item
    item = await update_watchlist_item(item_id, api_user["id"], body.schedule, body.status)
    if not item:
        raise APIError("not_found", "Watchlist item not found", 404)
    return {
        "id": item["id"],
        "company_url": item["company_url"],
        "schedule": item["schedule"],
        "status": item["status"],
        "next_run_at": item["next_run_at"].isoformat(),
    }


@router.delete("/watchlist/{item_id}", status_code=204, tags=["Watchlist"])
async def remove_from_watchlist(item_id: int, api_user: dict = Depends(require_api_key)):
    """Remove a company from the watchlist."""
    default_limiter.check(api_user["api_key_id"])
    from database import delete_watchlist_item
    deleted = await delete_watchlist_item(item_id, api_user["id"])
    if not deleted:
        raise APIError("not_found", "Watchlist item not found", 404)
    return JSONResponse(status_code=204, content=None)


@router.get("/watchlist/{item_id}/history", tags=["Watchlist"])
async def watchlist_history(item_id: int, api_user: dict = Depends(require_api_key)):
    """Get score change history for a watched company."""
    default_limiter.check(api_user["api_key_id"])
    from database import get_watchlist_item, get_score_history
    item = await get_watchlist_item(item_id, api_user["id"])
    if not item:
        raise APIError("not_found", "Watchlist item not found", 404)
    history = await get_score_history(item_id, api_user["id"])
    return {
        "item_id": item_id,
        "company_url": item["company_url"],
        "changes": [
            {
                "old_document_id": h["old_document_id"],
                "new_document_id": h["new_document_id"],
                "old_scores": {
                    "opportunity": h["old_opportunity_score"],
                    "pain": h["old_pain_score"],
                    "fit": h["old_fit_score"],
                    "timing": h["old_timing_score"],
                },
                "new_scores": {
                    "opportunity": h["new_opportunity_score"],
                    "pain": h["new_pain_score"],
                    "fit": h["new_fit_score"],
                    "timing": h["new_timing_score"],
                },
                "is_significant": h["is_significant"],
                "created_at": h["created_at"].isoformat(),
            }
            for h in history
        ],
    }
