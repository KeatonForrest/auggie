"""collect.py - Shared parallel data collection for the research pipeline.

All three pipeline entry points (web UI, API endpoint, async jobs) call
collect_enrichment_data() instead of duplicating the gather logic.
"""

import asyncio
from typing import Optional

from config import get_settings
from models import ScrapedContent
from services.news import NewsService
from services.edgar import EdgarService
from services.reviews import ReviewsService
from services.federal_register import FederalRegisterService
from services.retrieval import RetrievalService

# Module-level singletons (shared across callers within the same process)
news_service = NewsService()
edgar_service = EdgarService()
reviews_service = ReviewsService()
federal_register_service = FederalRegisterService()

_retrieval_service = None


def _get_retrieval_service() -> Optional[RetrievalService]:
    global _retrieval_service
    if _retrieval_service is None and get_settings().materials_enabled:
        _retrieval_service = RetrievalService()
    return _retrieval_service


async def collect_enrichment_data(
    scraped_content: ScrapedContent,
    company_name: str,
    user_id: int,
    *,
    verbose: bool = False,
) -> str:
    """Fetch news, EDGAR, reviews, Federal Register, and materials in parallel.

    Mutates scraped_content in place (sets news, edgar_filings, reviews,
    federal_regulations). Returns the retrieved_materials string.

    Args:
        scraped_content: Already-scraped website content to enrich.
        company_name: Clean domain-derived company name.
        user_id: Used for materials retrieval scoping.
        verbose: If True, print progress messages (web UI mode).

    Returns:
        Retrieved materials string (empty string if none).
    """
    settings = get_settings()

    async def _fetch_news():
        try:
            return await news_service.get_company_news(company_name)
        except Exception as e:
            if verbose:
                print(f"News fetch failed (non-fatal): {e}")
            return None

    async def _fetch_edgar_and_fedreg():
        edgar_content = None
        fed_content = None
        if settings.edgar_enabled:
            try:
                edgar_content = await edgar_service.get_company_filings(company_name)
            except Exception as e:
                if verbose:
                    print(f"EDGAR lookup failed (non-fatal): {e}")
        if settings.federal_register_enabled:
            try:
                fed_content = await federal_register_service.get_upcoming_regulations(
                    company_name=company_name,
                    sic_code=edgar_service._last_sic_code,
                )
            except Exception as e:
                if verbose:
                    print(f"Federal Register lookup failed (non-fatal): {e}")
        return edgar_content, fed_content

    async def _fetch_reviews():
        if not settings.reviews_enabled:
            return None
        try:
            return await reviews_service.get_reviews(company_name)
        except Exception as e:
            if verbose:
                print(f"Reviews scraping failed (non-fatal): {e}")
            return None

    async def _fetch_materials():
        retrieval = _get_retrieval_service()
        if not retrieval:
            return ""
        try:
            return await retrieval.get_relevant_context(
                user_id=user_id,
                company_name=company_name,
                company_description=scraped_content.homepage[:500] if scraped_content.homepage else "",
            ) or ""
        except Exception as e:
            if verbose:
                print(f"Materials retrieval failed (non-fatal): {e}")
            return ""

    if verbose:
        print(f"Fetching enrichment data for {company_name} (parallel)...")

    news_result, edgar_fedreg_result, reviews_result, materials_result = await asyncio.gather(
        _fetch_news(),
        _fetch_edgar_and_fedreg(),
        _fetch_reviews(),
        _fetch_materials(),
    )

    # Assign results
    if news_result:
        scraped_content.news = news_result
        if verbose:
            print("Found recent news articles")
    edgar_content, fed_content = edgar_fedreg_result
    if edgar_content:
        scraped_content.edgar_filings = edgar_content
        if verbose:
            print("Found SEC EDGAR filings")
    if fed_content:
        scraped_content.federal_regulations = fed_content
        if verbose:
            print("Found relevant regulations")
    if reviews_result:
        scraped_content.reviews = reviews_result
        if verbose:
            print("Found review data")

    return materials_result
