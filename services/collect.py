"""collect.py - Shared parallel data collection for the research pipeline.

All three pipeline entry points (web UI, API endpoint, async jobs) call
collect_enrichment_data() instead of duplicating the gather logic.
"""

import logging

import asyncio
from typing import Optional

import httpx

from config import get_settings
from models import ScrapedContent
from services.news import NewsService
from services.edgar import EdgarService
from services.federal_register import FederalRegisterService
from services.retrieval import RetrievalService

logger = logging.getLogger(__name__)

# Module-level singletons (shared across callers within the same process)
news_service = NewsService()
edgar_service = EdgarService()
federal_register_service = FederalRegisterService()

# Shared httpx client — created lazily on first use, reuses TCP connections
_http_client: Optional[httpx.AsyncClient] = None
_http_client_lock: Optional[asyncio.Lock] = None


async def get_shared_http_client() -> httpx.AsyncClient:
    """Get or create the shared httpx client with connection pooling."""
    global _http_client, _http_client_lock
    if _http_client_lock is None:
        _http_client_lock = asyncio.Lock()
    async with _http_client_lock:
        if _http_client is None or _http_client.is_closed:
            _http_client = httpx.AsyncClient(
                timeout=30.0,
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            )
    return _http_client


async def close_shared_http_client():
    """Close the shared client. Call on app shutdown."""
    global _http_client
    if _http_client is not None and not _http_client.is_closed:
        await _http_client.aclose()
        _http_client = None


_retrieval_service = None


def _get_retrieval_service() -> Optional[RetrievalService]:
    global _retrieval_service
    if _retrieval_service is None and get_settings().materials_enabled:
        _retrieval_service = RetrievalService()
    return _retrieval_service


def _extract_company_name(company_url: str) -> str:
    """Extract clean company name from a URL."""
    return company_url.replace("https://", "").replace("http://", "").split("/")[0].replace("www.", "")


async def collect_enrichment_data(
    scraped_content: ScrapedContent,
    company_url: str,
    user_id: int,
    *,
    verbose: bool = False,
) -> str:
    """Fetch news, EDGAR, reviews, Federal Register, and materials in parallel.

    Mutates scraped_content in place (sets news, edgar_filings, reviews,
    federal_regulations). Returns the retrieved_materials string.

    Args:
        scraped_content: Already-scraped website content to enrich.
        company_url: The company URL (name is extracted internally).
        user_id: Used for materials retrieval scoping.
        verbose: If True, print progress messages (web UI mode).

    Returns:
        Retrieved materials string (empty string if none).
    """
    company_name = _extract_company_name(company_url)
    settings = get_settings()

    client = await get_shared_http_client()

    async def _fetch_news():
        try:
            return await news_service.get_company_news(company_name, client=client)
        except Exception as e:
            if verbose:
                logger.error("News fetch failed (non-fatal): %s", e)
            return None

    async def _fetch_edgar():
        if not settings.edgar_enabled:
            return None
        try:
            return await edgar_service.get_company_filings(company_name, client=client)
        except Exception as e:
            if verbose:
                logger.error("EDGAR lookup failed (non-fatal): %s", e)
            return None

    async def _fetch_fedreg():
        """Fetch Federal Register data. Runs after EDGAR so SIC code is available."""
        if not settings.federal_register_enabled:
            return None
        try:
            return await federal_register_service.get_upcoming_regulations(
                company_name=company_name,
                sic_code=edgar_service._last_sic_code,
                client=client,
            )
        except Exception as e:
            if verbose:
                logger.error("Federal Register lookup failed (non-fatal): %s", e)
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
                logger.error("Materials retrieval failed (non-fatal): %s", e)
            return ""

    if verbose:
        logger.debug("Fetching enrichment data for %s (parallel)...", company_name)

    # Run EDGAR, news, materials in parallel
    news_result, edgar_content, materials_result = await asyncio.gather(
        _fetch_news(),
        _fetch_edgar(),
        _fetch_materials(),
    )

    # Federal Register depends on EDGAR's SIC code, so run after EDGAR completes
    fed_content = await _fetch_fedreg()

    # Assign results
    if news_result:
        scraped_content.news = news_result
        if verbose:
            logger.debug("Found recent news articles")
    if edgar_content:
        scraped_content.edgar_filings = edgar_content
        if verbose:
            logger.debug("Found SEC EDGAR filings")
    if fed_content:
        scraped_content.federal_regulations = fed_content
        if verbose:
            logger.debug("Found relevant regulations")
    return materials_result
