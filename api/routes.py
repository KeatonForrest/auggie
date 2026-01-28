"""v1 API routes — authenticated via API key."""

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from api.auth import require_api_key
from database import (
    get_user_by_id, get_user_usage, get_document,
    save_enriched_contacts, get_enriched_contacts,
    create_research_job, get_research_job, list_user_jobs,
    use_credit, refund_credit, record_api_usage,
)
from api.validation import validate_company_url
from api.jobs import run_research_job
from api.ratelimit import research_limiter, sequence_limiter, default_limiter

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
    return {"status": "ok", "user_id": api_user["user_id"]}


@router.post("/research", status_code=202)
async def create_research(body: ResearchRequest, api_user: dict = Depends(require_api_key)):
    """Start an async research job. Returns immediately with a job_id."""
    research_limiter.check(api_user["api_key_id"])
    user = await get_user_by_id(api_user["user_id"])
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    # Check and reserve credits upfront (refunded on failure)
    usage = await get_user_usage(user["id"])
    is_admin = usage.get("is_admin", False)
    if not is_admin:
        if usage.get("bonus_credits", 0) <= 0:
            raise HTTPException(status_code=402, detail="No credits remaining")
        reserved = await use_credit(user["id"])
        if not reserved:
            raise HTTPException(status_code=402, detail="No credits remaining")

    try:
        company_url = validate_company_url(body.company_url)
    except ValueError as e:
        # Refund if we reserved
        if not is_admin:
            await refund_credit(user["id"])
        raise HTTPException(status_code=422, detail=str(e))

    job = await create_research_job(user["id"], api_user["api_key_id"], company_url)

    asyncio.create_task(
        run_research_job(job["id"], user["id"], api_user["api_key_id"], company_url, is_admin=is_admin)
    )

    return {"job_id": job["id"], "status": "processing"}


@router.get("/research/{job_id}")
async def get_job_status(job_id: int, api_user: dict = Depends(require_api_key)):
    """Poll for job status. Returns full result when completed."""
    default_limiter.check(api_user["api_key_id"])
    job = await get_research_job(job_id, api_user["user_id"])
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    result = {
        "job_id": job["id"],
        "status": job["status"],
        "company_url": job["company_url"],
        "created_at": job["created_at"].isoformat(),
        "completed_at": job["completed_at"].isoformat() if job["completed_at"] else None,
    }

    if job["status"] == "failed":
        result["error"] = job["error_message"]

    if job["status"] == "completed" and job["document_id"]:
        doc = await get_document(job["document_id"], api_user["user_id"])
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
    jobs = await list_user_jobs(api_user["user_id"])
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

    user = await get_user_by_id(api_user["user_id"])
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    document = await get_document(body.document_id, user_id=user["id"])
    if not document:
        return EnrichResponse(success=False, error="Document not found")

    # Check if already enriched
    existing = await get_enriched_contacts(body.document_id, user["id"])
    if existing:
        return EnrichResponse(
            success=True,
            contacts=[EnrichContact(**{k: v for k, v in c.items() if k in EnrichContact.model_fields}) for c in existing],
            cached=True,
        )

    # Check credits (enrichment = 50 cents = 0.5 credits)
    usage = await get_user_usage(user["id"])
    is_admin = usage.get("is_admin", False)
    if not is_admin and usage.get("bonus_credits", 0) < 50:
        return EnrichResponse(success=False, error="Insufficient credits (enrichment costs 0.5 credits)")

    # Use custom titles or fall back to user's ICP
    titles = body.titles
    if not titles:
        titles = _build_default_titles(user)

    company_domain = document.company_url.replace("https://", "").replace("http://", "").split("/")[0].replace("www.", "")

    try:
        contacts = await leadmagic.enrich_contacts(
            company_domain=company_domain,
            company_name=document.company_name,
            target_titles=titles,
        )

        if contacts:
            await save_enriched_contacts(body.document_id, user["id"], contacts)
            if not is_admin:
                await use_credit(user["id"], cents=50)

        await record_api_usage(api_user["api_key_id"], "/v1/enrich", 1)

        return EnrichResponse(
            success=True,
            contacts=[EnrichContact(**c) for c in contacts],
            cached=False,
        )
    except Exception as e:
        return EnrichResponse(success=False, error=str(e))


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

    user = await get_user_by_id(api_user["user_id"])
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    document = await get_document(doc_id, user_id=user["id"])
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    from services.writing import WritingService
    writing_service = WritingService()

    try:
        emails = await writing_service.generate_email_sequence(
            document=document,
            product_context=user.get("product_context", ""),
        )

        await record_api_usage(api_user["api_key_id"], "/v1/research/sequence", 0)

        return SequenceResponse(
            success=True,
            document_id=doc_id,
            emails=[SequenceEmail(**e) for e in emails],
        )
    except Exception as e:
        return SequenceResponse(success=False, document_id=doc_id, error=str(e))
