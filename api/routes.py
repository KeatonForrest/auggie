"""v1 API routes — authenticated via API key."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import require_api_key
from database import (
    get_user_by_id, get_user_usage, save_document, use_credit,
    record_api_usage, get_document, save_enriched_contacts, get_enriched_contacts,
)
from services.firecrawl import FirecrawlService
from services.claude import ClaudeService
from services.wappalyzer import WappalyzerService
from services.news import NewsService
from config import get_settings
from services.retrieval import RetrievalService

_retrieval_service = None

def _get_retrieval_service():
    global _retrieval_service
    if _retrieval_service is None and get_settings().materials_enabled:
        _retrieval_service = RetrievalService()
    return _retrieval_service

router = APIRouter(prefix="/v1", tags=["v1"])

firecrawl_service = FirecrawlService()
claude_service = ClaudeService()
wappalyzer_service = WappalyzerService()
news_service = NewsService()


from api.validation import validate_company_url


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
    return {"status": "ok", "user_id": api_user["user_id"]}


@router.post("/research", response_model=ResearchResponse)
async def create_research(body: ResearchRequest, api_user: dict = Depends(require_api_key)):
    """Run full research pipeline on a company. Returns JSON with scores and sections."""
    user = await get_user_by_id(api_user["user_id"])
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    # Check credits
    usage = await get_user_usage(user["id"])
    is_admin = usage.get("is_admin", False)
    if not is_admin and usage.get("bonus_credits", 0) <= 0:
        return ResearchResponse(success=False, error="No credits remaining")

    try:
        company_url = validate_company_url(body.company_url)
    except ValueError as e:
        return ResearchResponse(success=False, error=str(e))

    try:
        scraped_content = await firecrawl_service.scrape_company(company_url)

        tech_by_domain = await wappalyzer_service.analyze_multiple_domains(
            main_url=company_url,
            main_html=scraped_content.homepage_html,
        )

        company_name = company_url.replace("https://", "").replace("http://", "").split("/")[0].replace("www.", "")
        news_content = await news_service.get_company_news(company_name)
        if news_content:
            scraped_content.news = news_content

        retrieved_materials = ""
        retrieval = _get_retrieval_service()
        if retrieval:
            try:
                retrieved_materials = await retrieval.get_relevant_context(
                    user_id=user["id"],
                    company_name=company_name,
                    company_description=scraped_content.homepage[:500] if scraped_content.homepage else "",
                )
            except Exception:
                pass

        document = await claude_service.generate_research_document(
            company_url=company_url,
            scraped=scraped_content,
            product_context=user.get("product_context", ""),
            tech_by_domain=tech_by_domain,
            retrieved_materials=retrieved_materials,
            seller_company=user.get("company_name", ""),
        )

        doc_id = await save_document(document, user_id=user["id"])
        if not is_admin:
            await use_credit(user["id"])

        # Track API usage
        await record_api_usage(api_user["api_key_id"], "/v1/research", 1)

        return ResearchResponse(
            success=True,
            document_id=doc_id,
            company_name=document.company_name,
            company_url=document.company_url,
            scores=ScoreResponse(
                composite=document.opportunity_score,
                pain=document.pain_score,
                fit=document.fit_score,
                timing=document.timing_score,
                summary=document.score_summary,
            ),
            sections={
                "company_overview": document.company_overview,
                "projects_initiatives": document.projects_initiatives,
                "confirmed_tech_stack": document.confirmed_tech_stack,
                "hiring_signals": document.hiring_signals,
                "business_problems": document.business_problems,
                "existential_data_points": document.existential_data_points,
                "product_fit": document.product_fit,
                "talking_points": document.talking_points,
                "recent_news": document.recent_news,
                "key_contacts": document.key_contacts,
                "information_gaps": document.information_gaps,
            },
        )

    except Exception as e:
        return ResearchResponse(success=False, error=str(e))


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
