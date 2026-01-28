"""Background job runner for async research."""

import asyncio
import logging

import httpx

from database import (
    get_user_by_id, save_document,
    record_api_usage, update_job_status, get_user_webhook,
    create_webhook_delivery, update_delivery_status, refund_credit,
)
from services.firecrawl import FirecrawlService
from services.claude import ClaudeService
from services.wappalyzer import WappalyzerService
from services.news import NewsService
from services.retrieval import RetrievalService
from config import get_settings
from api.webhooks import sign_payload

logger = logging.getLogger(__name__)

firecrawl_service = FirecrawlService()
claude_service = ClaudeService()
wappalyzer_service = WappalyzerService()
news_service = NewsService()

_retrieval_service = None

def _get_retrieval_service():
    global _retrieval_service
    if _retrieval_service is None and get_settings().materials_enabled:
        _retrieval_service = RetrievalService()
    return _retrieval_service


async def run_research_job(job_id: int, user_id: int, api_key_id: int, company_url: str, *, is_admin: bool = False):
    """Execute the research pipeline in the background and update job status.

    Credit is reserved before this function is called. On failure, non-admin
    users get their credit refunded.
    """
    try:
        user = await get_user_by_id(user_id)
        if not user:
            if not is_admin:
                await refund_credit(user_id)
            await update_job_status(job_id, "failed", error_message="User not found")
            return

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
                    user_id=user_id,
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

        doc_id = await save_document(document, user_id=user_id)

        await record_api_usage(api_key_id, "/v1/research", 1)
        await update_job_status(job_id, "completed", document_id=doc_id)

        # Fire webhook
        await _deliver_webhook(user_id, job_id, "completed", doc_id, None)

    except Exception as e:
        logger.exception("Research job %s failed", job_id)
        if not is_admin:
            await refund_credit(user_id)
        error_msg = str(e)[:500]
        await update_job_status(job_id, "failed", error_message=error_msg)
        await _deliver_webhook(user_id, job_id, "failed", None, error_msg)


async def _deliver_webhook(user_id: int, job_id: int, status: str, document_id: int | None, error: str | None):
    """Send webhook notification if the user has one configured."""
    webhook = await get_user_webhook(user_id)
    if not webhook:
        return

    payload = {
        "job_id": job_id,
        "status": status,
        "document_id": document_id,
        "error": error,
    }

    delivery = await create_webhook_delivery(webhook["id"], job_id)

    try:
        signature = sign_payload(payload, webhook["secret"])
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                webhook["url"],
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "X-Webhook-Signature": f"sha256={signature}",
                },
            )
        await update_delivery_status(
            delivery["id"],
            status="success" if resp.status_code < 400 else "failed",
            http_status=resp.status_code,
        )
    except Exception as e:
        await update_delivery_status(
            delivery["id"],
            status="failed",
            error_message=str(e)[:500],
        )
