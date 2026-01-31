"""v1 API routes — authenticated via API key."""

import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from api.auth import require_api_key
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
from db.jobs import create_job_with_credit, create_research_job
from api.ratelimit import research_limiter, sequence_limiter, default_limiter, bulk_limiter, clay_limiter

router = APIRouter(prefix="/v1", tags=["v1"])


class ResearchRequest(BaseModel):
    company_url: str


class ScoreResponse(BaseModel):
    composite: int | None = None
    pain: int | None = None
    fit: int | None = None
    timing: int | None = None
    summary: str | None = None


class ResearchResponse(BaseModel):
    success: bool
    document_id: int | None = None
    company_name: str | None = None
    company_url: str | None = None
    scores: ScoreResponse | None = None
    sections: dict | None = None
    error: str | None = None


@router.get("/ping")
async def ping(api_user: dict = Depends(require_api_key)):
    """Health check endpoint. Returns 200 if API key is valid."""
    default_limiter.check(api_user["api_key_id"])
    return {"status": "ok", "user_id": api_user["id"]}


@router.post("/research", status_code=202)
async def create_research(body: ResearchRequest, api_user: dict = Depends(require_api_key)):
    """Start an async research job. Returns immediately with a job_id."""
    research_limiter.check(api_user["api_key_id"])

    try:
        company_url = validate_company_url(body.company_url)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # Atomically reserve credit + create job
    usage = await get_user_usage(api_user["id"])
    is_admin = usage.get("is_admin", False)
    if not is_admin:
        try:
            job = await create_job_with_credit(api_user["id"], api_user["api_key_id"], company_url)
        except ValueError:
            raise HTTPException(status_code=402, detail="No credits remaining")
    else:
        job = await create_research_job(api_user["id"], api_user["api_key_id"], company_url)

    await create_tracked_task(
        "research",
        {"job_id": job["id"], "user_id": api_user["id"], "api_key_id": api_user["api_key_id"], "company_url": company_url, "is_admin": is_admin},
        name=f"research-{job['id']}",
    )

    return {"job_id": job["id"], "status": "processing"}


@router.get("/research/{job_id}")
async def get_job_status(job_id: int, api_user: dict = Depends(require_api_key)):
    """Poll for job status. Returns full result when completed."""
    default_limiter.check(api_user["api_key_id"])
    job = await get_research_job(job_id, api_user["id"])
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

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
            result["document_id"] = job["document_id"]
            result["company_name"] = doc.company_name
            result["scores"] = {
                "composite": doc.opportunity_score,
                "pain": doc.pain_score,
                "fit": doc.fit_score,
                "timing": doc.timing_score,
                "summary": doc.score_summary,
            }
            result["sections"] = {
                "company_overview": doc.company_overview,
                "projects_initiatives": doc.projects_initiatives,
                "confirmed_tech_stack": doc.confirmed_tech_stack,
                "hiring_signals": doc.hiring_signals,
                "business_problems": doc.business_problems,
                "existential_data_points": doc.existential_data_points,
                "product_fit": doc.product_fit,
                "talking_points": doc.talking_points,
                "recent_news": doc.recent_news,
                "key_contacts": doc.key_contacts,
                "information_gaps": doc.information_gaps,
            }

    return result


@router.get("/research")
async def list_jobs(api_user: dict = Depends(require_api_key)):
    """List the user's recent research jobs."""
    default_limiter.check(api_user["api_key_id"])
    jobs = await list_user_jobs(api_user["id"])
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
        ]
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


@router.post("/enrich", response_model=EnrichResponse)
async def enrich_contacts(body: EnrichRequest, api_user: dict = Depends(require_api_key)):
    """Enrich contacts for an existing research document using LeadMagic."""
    research_limiter.check(api_user["api_key_id"])
    from services.leadmagic import LeadMagicService
    leadmagic = LeadMagicService()

    if not leadmagic.is_configured():
        return EnrichResponse(success=False, error="Contact enrichment is not yet configured.")

    document = await get_document(body.document_id, user_id=api_user["id"])
    if not document:
        return EnrichResponse(success=False, error="Document not found")

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
        return EnrichResponse(success=False, error="Insufficient credits (enrichment costs 0.5 credits)")

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

        return EnrichResponse(
            success=True,
            contacts=[EnrichContact(**c) for c in contacts],
            cached=False,
        )
    except Exception as e:
        return EnrichResponse(success=False, error=str(e))



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


def _build_clay_response(doc, *, cached: bool, duration: float | None = None, error: str | None = None) -> dict:
    """Build flat Clay-friendly response from a ResearchDocument."""
    return {
        "success": True,
        "company_name": doc.company_name,
        "company_url": doc.company_url,
        "pain_score": doc.pain_score,
        "fit_score": doc.fit_score,
        "timing_score": doc.timing_score,
        "composite_score": doc.opportunity_score,
        "score_summary": _truncate(doc.score_summary),
        "pain_reasons": _truncate(doc.score_summary or doc.business_problems),
        "business_problems": _truncate(doc.business_problems),
        "product_fit": _truncate(doc.product_fit),
        "talking_points": _truncate(doc.talking_points),
        "existential_data_points": _truncate(doc.existential_data_points),
        "document_id": doc.id,
        "cached": cached,
        "research_duration_seconds": round(duration, 2) if duration is not None else None,
        "error": error,
    }


@router.post("/clay/enrich")
async def clay_enrich(body: ClayEnrichRequest, api_user: dict = Depends(require_api_key)):
    """Synchronous enrichment endpoint optimized for Clay HTTP columns.

    Runs the full research pipeline and returns a flat JSON response.
    Uses 24-hour caching to avoid duplicate costs.
    """
    clay_limiter.check(api_user["api_key_id"])

    # Validate URL
    try:
        company_url = validate_company_url(body.company_url)
    except ValueError as e:
        return JSONResponse(content={"success": False, "error": str(e)})

    # Check 24h cache
    cached_doc = await get_recent_document_by_url(api_user["id"], company_url)
    if cached_doc:
        await record_api_usage(api_user["api_key_id"], "/v1/clay/enrich", 0)
        return _build_clay_response(cached_doc, cached=True)

    # Atomically reserve credit + create job
    usage = await get_user_usage(api_user["id"])
    is_admin = usage.get("is_admin", False)
    if not is_admin:
        try:
            job = await create_job_with_credit(api_user["id"], api_user["api_key_id"], company_url)
        except ValueError:
            return JSONResponse(content={"success": False, "error": "No credits remaining"})
    else:
        job = await create_research_job(api_user["id"], api_user["api_key_id"], company_url)

    # Run pipeline synchronously
    start = time.monotonic()
    try:
        doc_id = await _run_research_pipeline(api_user["id"], company_url)
        duration = time.monotonic() - start

        await record_api_usage(api_user["api_key_id"], "/v1/clay/enrich", 1)
        from database import update_job_status
        await update_job_status(job["id"], "completed", document_id=doc_id)

        doc = await get_document(doc_id, api_user["id"])
        return _build_clay_response(doc, cached=False, duration=duration)

    except Exception as e:
        duration = time.monotonic() - start
        if not is_admin:
            await refund_credit(api_user["id"])
        from database import update_job_status
        await update_job_status(job["id"], "failed", error_message=str(e)[:500])
        return JSONResponse(
            content={"success": False, "error": str(e)[:500]},
        )


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


@router.post("/research/{doc_id}/sequence", response_model=SequenceResponse)
async def generate_sequence(doc_id: int, api_user: dict = Depends(require_api_key)):
    """Generate a 3-email outreach sequence from a completed research document."""
    sequence_limiter.check(api_user["api_key_id"])

    document = await get_document(doc_id, user_id=api_user["id"])
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    from services.instances import writing_service

    try:
        emails = await writing_service.generate_email_sequence(
            document=document,
            product_context=api_user.get("product_context", ""),
            product_type=api_user.get("product_type", "saas"),
        )

        await record_api_usage(api_user["api_key_id"], "/v1/research/sequence", 0)

        return SequenceResponse(
            success=True,
            document_id=doc_id,
            emails=[SequenceEmail(**e) for e in emails],
        )
    except Exception as e:
        return SequenceResponse(success=False, document_id=doc_id, error=str(e))


# =============================================================================
# Bulk Research
# =============================================================================

class BulkResearchRequest(BaseModel):
    company_urls: list[str]
    name: str | None = None


@router.post("/research/bulk", status_code=202)
async def create_bulk_research(body: BulkResearchRequest, api_user: dict = Depends(require_api_key)):
    """Start a bulk research job. Accepts up to 100 URLs."""
    bulk_limiter.check(api_user["api_key_id"])

    if not body.company_urls:
        raise HTTPException(status_code=422, detail="company_urls must not be empty")
    if len(body.company_urls) > 100:
        raise HTTPException(status_code=422, detail="Maximum 100 URLs per bulk job")

    # Validate all URLs upfront
    validated_urls = []
    for url in body.company_urls:
        try:
            validated_urls.append(validate_company_url(url))
        except ValueError as e:
            raise HTTPException(status_code=422, detail=f"Invalid URL '{url}': {e}")

    # Reserve credits upfront atomically
    n = len(validated_urls)
    usage = await get_user_usage(api_user["id"])
    is_admin = usage.get("is_admin", False)
    if not is_admin:
        credits_needed = n * 100  # cents
        ok = await use_credit(api_user["id"], cents=credits_needed)
        if not ok:
            raise HTTPException(status_code=402, detail=f"Insufficient credits. Need {n}, have {usage.get('bonus_credits', 0) // 100}")

    bulk_job = await create_bulk_job(api_user["id"], api_user["api_key_id"], body.name, n, n * 100)
    await create_bulk_job_items(bulk_job["id"], validated_urls)

    await create_tracked_task(
        "bulk",
        {"bulk_job_id": bulk_job["id"], "user_id": api_user["id"], "api_key_id": api_user["api_key_id"], "is_admin": is_admin},
        name=f"bulk-{bulk_job['id']}",
    )

    return {"bulk_job_id": bulk_job["id"], "status": "processing", "total_items": n}


@router.get("/research/bulk/{bulk_job_id}")
async def get_bulk_job_status(bulk_job_id: int, api_user: dict = Depends(require_api_key)):
    """Get bulk job progress and all items."""
    default_limiter.check(api_user["api_key_id"])
    job = await get_bulk_job(bulk_job_id, api_user["id"])
    if not job:
        raise HTTPException(status_code=404, detail="Bulk job not found")

    items = await get_bulk_job_items(bulk_job_id)

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


@router.get("/research/bulk")
async def list_bulk_jobs_endpoint(api_user: dict = Depends(require_api_key)):
    """List recent bulk jobs (summaries only)."""
    default_limiter.check(api_user["api_key_id"])
    jobs = await list_bulk_jobs(api_user["id"])
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
        ]
    }


# =============================================================================
# Lists
# =============================================================================

class CreateListRequest(BaseModel):
    name: str
    company_urls: list[str]
    analyze: bool = False


@router.post("/lists", status_code=201)
async def create_list_endpoint(body: CreateListRequest, api_user: dict = Depends(require_api_key)):
    """Create a persistent list of companies. Optionally trigger analysis immediately."""
    bulk_limiter.check(api_user["api_key_id"])

    if not body.company_urls:
        raise HTTPException(status_code=422, detail="company_urls must not be empty")
    if len(body.company_urls) > 100:
        raise HTTPException(status_code=422, detail="Maximum 100 URLs per list")
    if not body.name or not body.name.strip():
        raise HTTPException(status_code=422, detail="name is required")

    # Validate and deduplicate URLs upfront
    validated_urls = []
    seen = set()
    for url in body.company_urls:
        try:
            v = validate_company_url(url)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=f"Invalid URL '{url}': {e}")
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
            raise HTTPException(status_code=402, detail=f"Insufficient credits. Need {n}, have {usage.get('bonus_credits', 0) // 100}")

    lst = await create_list(api_user["id"], api_user["api_key_id"], body.name.strip())
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

    return {
        "list_id": lst["id"],
        "name": lst["name"],
        "status": status,
        "total_accounts": n,
    }


@router.post("/lists/{list_id}/analyze", status_code=202)
async def analyze_list_endpoint(list_id: int, api_user: dict = Depends(require_api_key)):
    """Trigger analysis on a list's pending accounts."""
    bulk_limiter.check(api_user["api_key_id"])

    lst = await get_list(list_id, api_user["id"])
    if not lst:
        raise HTTPException(status_code=404, detail="List not found")

    # Atomic status transition — prevents concurrent analysis starts
    started = await try_start_list_analysis(list_id)
    if not started:
        raise HTTPException(status_code=409, detail="List is already being analyzed")

    pending = await get_pending_list_accounts(list_id)
    if not pending:
        raise HTTPException(status_code=422, detail="No pending accounts to analyze")

    n = len(pending)
    usage = await get_user_usage(api_user["id"])
    is_admin = usage.get("is_admin", False)

    if not is_admin:
        credits_needed = n * 100
        ok = await use_credit(api_user["id"], cents=credits_needed)
        if not ok:
            raise HTTPException(status_code=402, detail=f"Insufficient credits. Need {n}, have {usage.get('bonus_credits', 0) // 100}")

    await update_list_credits(list_id, (lst["credits_reserved"] or 0) + n * 100)
    await create_tracked_task(
        "list_analysis",
        {"list_id": list_id, "user_id": api_user["id"], "api_key_id": api_user["api_key_id"], "is_admin": is_admin},
        name=f"list-analyze-{list_id}",
    )

    return {"list_id": list_id, "status": "analyzing", "pending_accounts": n}


@router.get("/lists/{list_id}")
async def get_list_endpoint(
    list_id: int,
    api_user: dict = Depends(require_api_key),
    min_pain_score: int | None = None,
    min_composite_score: int | None = None,
    sort_by: str = "composite_score",
    order: str = "desc",
    limit: int = 100,
    offset: int = 0,
):
    """Get list details with accounts, optional filtering/sorting."""
    default_limiter.check(api_user["api_key_id"])

    lst = await get_list(list_id, api_user["id"])
    if not lst:
        raise HTTPException(status_code=404, detail="List not found")

    accounts = await get_list_accounts(
        list_id,
        min_pain=min_pain_score,
        min_composite=min_composite_score,
        sort_by=sort_by,
        order=order,
        limit=limit,
        offset=offset,
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
    }


@router.get("/lists")
async def list_lists_endpoint(api_user: dict = Depends(require_api_key)):
    """List user's recent lists (summaries, no accounts)."""
    default_limiter.check(api_user["api_key_id"])
    lists = await db_list_lists(api_user["id"])
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
        ]
    }


@router.delete("/lists/{list_id}", status_code=204)
async def delete_list_endpoint(list_id: int, api_user: dict = Depends(require_api_key)):
    """Delete a list and all its accounts."""
    default_limiter.check(api_user["api_key_id"])
    deleted = await delete_list(list_id, api_user["id"])
    if not deleted:
        raise HTTPException(status_code=404, detail="List not found")
    return JSONResponse(status_code=204, content=None)


class PushInstantlyRequest(BaseModel):
    campaign_id: str
    account_ids: list[int] | None = None


@router.post("/lists/{list_id}/push")
async def push_list_to_instantly(list_id: int, body: PushInstantlyRequest, api_user: dict = Depends(require_api_key)):
    """Push accounts from a list to an Instantly campaign via API."""
    from database import get_integration, get_enriched_contacts as get_contacts
    from services.instantly import push_accounts_to_instantly

    default_limiter.check(api_user["api_key_id"])

    lst = await get_list(list_id, api_user["id"])
    if not lst:
        raise HTTPException(status_code=404, detail="List not found")

    integration = await get_integration(api_user["id"], "instantly")
    if not integration:
        raise HTTPException(status_code=400, detail="Instantly not connected")

    all_accounts = await get_list_accounts(list_id)
    if body.account_ids:
        accounts = [a for a in all_accounts if a["id"] in body.account_ids]
    else:
        accounts = [a for a in all_accounts if a.get("status") == "completed"]

    if not accounts:
        raise HTTPException(status_code=400, detail="No accounts to push")

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


@router.get("/team")
async def api_list_team(api_user: dict = Depends(require_api_key)):
    """List team members."""
    from database import get_org_members, get_user_by_id
    user = await get_user_by_id(api_user["id"])
    if not user or not user.get("org_id"):
        raise HTTPException(status_code=400, detail="No organization found")
    members = await get_org_members(user["org_id"])
    return {"members": members}


@router.post("/team/invite")
async def api_invite_member(body: InviteRequest, api_user: dict = Depends(require_api_key)):
    """Invite a team member (admin only)."""
    from database import get_user_by_id, create_org_invite
    user = await get_user_by_id(api_user["id"])
    if not user or user.get("org_role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    if body.role not in ("admin", "member", "viewer"):
        raise HTTPException(status_code=400, detail="Invalid role")
    invite = await create_org_invite(user["org_id"], body.email, body.role, user["id"])
    return {"invite": {"id": invite["id"], "email": invite["email"], "role": invite["role"], "token": invite["token"], "expires_at": str(invite["expires_at"])}}


@router.delete("/team/members/{member_id}")
async def api_remove_member(member_id: int, api_user: dict = Depends(require_api_key)):
    """Remove a team member (admin only)."""
    from database import get_user_by_id, remove_org_member
    user = await get_user_by_id(api_user["id"])
    if not user or user.get("org_role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    if member_id == user["id"]:
        raise HTTPException(status_code=400, detail="Cannot remove yourself")
    removed = await remove_org_member(user["org_id"], member_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Member not found")
    return {"removed": True}


@router.patch("/team/members/{member_id}")
async def api_change_role(member_id: int, body: RoleUpdate, api_user: dict = Depends(require_api_key)):
    """Change a team member's role (admin only)."""
    from database import get_user_by_id, update_member_role
    user = await get_user_by_id(api_user["id"])
    if not user or user.get("org_role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    if member_id == user["id"]:
        raise HTTPException(status_code=400, detail="Cannot change your own role")
    if body.role not in ("admin", "member", "viewer"):
        raise HTTPException(status_code=400, detail="Invalid role")
    updated = await update_member_role(user["org_id"], member_id, body.role)
    if not updated:
        raise HTTPException(status_code=404, detail="Member not found")
    return {"updated": True}
