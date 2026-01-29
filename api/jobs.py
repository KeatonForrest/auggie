"""Background job runner for async research."""

import asyncio
import logging

import httpx

from database import (
    get_user_by_id, save_document, get_document,
    record_api_usage, update_job_status, get_user_webhook,
    create_webhook_delivery, update_delivery_status, refund_credit,
    create_research_job, get_bulk_job_items, update_bulk_job_item,
    finalize_bulk_job,
    get_pending_list_accounts, update_list_account,
    finalize_list, get_list_source, get_list_accounts,
)
from services.collect import collect_enrichment_data
from services.instances import firecrawl_service, claude_service, wappalyzer_service
from config import get_settings
from api.webhooks import sign_payload

logger = logging.getLogger(__name__)


async def _run_research_pipeline(user_id: int, company_url: str) -> int:
    """Execute the core research pipeline: scrape, analyze, save.

    Returns the document ID on success. Raises on failure.
    """
    user = await get_user_by_id(user_id)
    if not user:
        raise RuntimeError("User not found")

    scraped_content = await firecrawl_service.scrape_company(company_url)

    tech_by_domain = await wappalyzer_service.analyze_multiple_domains(
        main_url=company_url,
        main_html=scraped_content.homepage_html,
    )

    retrieved_materials = await collect_enrichment_data(
        scraped_content, company_url, user_id,
    )

    document = await claude_service.generate_research_document(
        company_url=company_url,
        scraped=scraped_content,
        product_context=user.get("product_context", ""),
        tech_by_domain=tech_by_domain,
        retrieved_materials=retrieved_materials,
        seller_company=user.get("company_name", ""),
        target_personas=user.get("target_personas", ""),
        target_industries=user.get("target_industries", ""),
        problems_solved=user.get("problems_solved", ""),
    )

    doc_id = await save_document(document, user_id=user_id)
    return doc_id


async def run_research_job(job_id: int, user_id: int, api_key_id: int | None, company_url: str, *, is_admin: bool = False):
    """Execute the research pipeline in the background and update job status.

    Credit is reserved before this function is called. On failure, non-admin
    users get their credit refunded.
    """
    try:
        doc_id = await _run_research_pipeline(user_id, company_url)

        if api_key_id is not None:
            await record_api_usage(api_key_id, "/v1/research", 1)
        await update_job_status(job_id, "completed", document_id=doc_id)

        # Slack notification
        try:
            from services.notifications import send_slack_notification
            from database import get_integration as _get_integ
            slack = await _get_integ(user_id, "slack")
            if slack:
                doc = await get_document(doc_id, user_id)
                settings = get_settings()
                notify_data = {
                    "company_name": doc.company_name if doc else company_url,
                    "company_url": company_url,
                    "pain_score": doc.pain_score if doc else None,
                    "composite_score": doc.opportunity_score if doc else None,
                    "doc_url": f"{settings.app_url}/document/{doc_id}",
                }
                await send_slack_notification(slack["access_token"], "research_complete", notify_data)
                if doc and doc.pain_score is not None and doc.pain_score >= 80:
                    await send_slack_notification(slack["access_token"], "high_pain_alert", notify_data)
        except Exception:
            logger.exception("Slack notification failed for job %s", job_id)

        # Fire webhook
        await _deliver_webhook(user_id, job_id, "completed", doc_id, None)

    except Exception as e:
        logger.exception("Research job %s failed", job_id)
        if not is_admin:
            await refund_credit(user_id)
        error_msg = str(e)[:500]
        await update_job_status(job_id, "failed", error_message=error_msg)
        await _deliver_webhook(user_id, job_id, "failed", None, error_msg)


async def run_bulk_job(bulk_job_id: int, user_id: int, api_key_id: int, is_admin: bool = False):
    """Process all items in a bulk job with bounded concurrency."""
    items = await get_bulk_job_items(bulk_job_id)
    semaphore = asyncio.Semaphore(5)

    async def process_item(item: dict):
        async with semaphore:
            item_id = item["id"]
            company_url = item["company_url"]

            # Create a research job for tracking
            job = await create_research_job(user_id, api_key_id, company_url)
            await update_bulk_job_item(item_id, "processing", research_job_id=job["id"])

            try:
                doc_id = await _run_research_pipeline(user_id, company_url)

                await record_api_usage(api_key_id, "/v1/research", 1)
                await update_job_status(job["id"], "completed", document_id=doc_id)
                await update_bulk_job_item(item_id, "completed", research_job_id=job["id"], document_id=doc_id)

            except Exception as e:
                logger.exception("Bulk item %s failed for %s", item_id, company_url)
                error_msg = str(e)[:500]
                await update_job_status(job["id"], "failed", error_message=error_msg)
                await update_bulk_job_item(item_id, "failed", research_job_id=job["id"], error_message=error_msg)

    # Process in batches of 20 to limit memory usage
    BATCH_SIZE = 20
    for batch_start in range(0, len(items), BATCH_SIZE):
        batch = items[batch_start:batch_start + BATCH_SIZE]
        results = await asyncio.gather(*(process_item(item) for item in batch), return_exceptions=True)
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error("Bulk item %s raised unhandled exception: %s", batch[i]["id"], result)

    # Finalize and refund failed credits
    final = await finalize_bulk_job(bulk_job_id)
    failed_count = final["failed_items"]
    if failed_count > 0 and not is_admin:
        await refund_credit(user_id, cents=failed_count * 100)

    # Fire webhook for bulk completion
    await _deliver_webhook(user_id, bulk_job_id, f"bulk_{final['status']}", None, None)


async def run_list_analysis(list_id: int, user_id: int, api_key_id: int | None = None, is_admin: bool = False):
    """Process all pending accounts in a list with bounded concurrency."""
    accounts = await get_pending_list_accounts(list_id)
    semaphore = asyncio.Semaphore(5)

    async def process_account(account: dict):
        async with semaphore:
            account_id = account["id"]
            company_url = account["company_url"]

            job = await create_research_job(user_id, api_key_id, company_url)
            await update_list_account(account_id, "processing", research_job_id=job["id"])

            try:
                doc_id = await _run_research_pipeline(user_id, company_url)

                if api_key_id is not None:
                    await record_api_usage(api_key_id, "/v1/research", 1)
                await update_job_status(job["id"], "completed", document_id=doc_id)

                # Extract scores from the saved document
                doc = await get_document(doc_id, user_id)
                await update_list_account(
                    account_id, "completed",
                    document_id=doc_id,
                    research_job_id=job["id"],
                    pain_score=doc.pain_score,
                    fit_score=doc.fit_score,
                    timing_score=doc.timing_score,
                    composite_score=doc.opportunity_score,
                    company_name=doc.company_name,
                )

                # Fire account_scored automation rules
                try:
                    from services.automation import evaluate_rules
                    from api.tasks import create_tracked_task
                    scored_account = {
                        "id": account_id,
                        "status": "completed",
                        "document_id": doc_id,
                        "pain_score": doc.pain_score,
                        "fit_score": doc.fit_score,
                        "timing_score": doc.timing_score,
                        "composite_score": doc.opportunity_score,
                        "company_name": doc.company_name,
                    }
                    create_tracked_task(
                        evaluate_rules(user_id, "account_scored", {
                            "list_id": list_id,
                            "accounts": [scored_account],
                        }),
                        name=f"automation-scored-{account_id}",
                    )
                except Exception:
                    logger.exception("account_scored automation failed for account %s", account_id)

            except Exception as e:
                logger.exception("List account %s failed for %s", account_id, company_url)
                error_msg = str(e)[:500]
                await update_job_status(job["id"], "failed", error_message=error_msg)
                await update_list_account(
                    account_id, "failed",
                    research_job_id=job["id"],
                    error_message=error_msg,
                )

    # Process in batches of 20 to limit memory usage
    BATCH_SIZE = 20
    for batch_start in range(0, len(accounts), BATCH_SIZE):
        batch = accounts[batch_start:batch_start + BATCH_SIZE]
        results = await asyncio.gather(*(process_account(a) for a in batch), return_exceptions=True)
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error("List account %s raised unhandled exception: %s", batch[i]["id"], result)

    # Finalize and refund failed credits
    final = await finalize_list(list_id)
    failed_count = final["failed_accounts"]
    if failed_count > 0 and not is_admin:
        await refund_credit(user_id, cents=failed_count * 100)

    # HubSpot writeback: if list was imported from HubSpot, push scores back
    try:
        source = await get_list_source(list_id)
        if source and source.get("provider") == "hubspot":
            from services.hubspot import write_list_scores_to_hubspot
            all_accounts = await get_list_accounts(list_id)
            updated = await write_list_scores_to_hubspot(user_id, source, all_accounts)
            logger.info("HubSpot writeback: updated %d companies for list %d", updated, list_id)
    except Exception:
        logger.exception("HubSpot writeback failed for list %d", list_id)

    # Salesforce writeback: if list was imported from Salesforce, push scores back
    try:
        if not source:
            source = await get_list_source(list_id)
        if source and source.get("provider") == "salesforce":
            from services.salesforce import write_list_scores_to_salesforce
            all_accounts = await get_list_accounts(list_id)
            updated = await write_list_scores_to_salesforce(user_id, source, all_accounts)
            logger.info("Salesforce writeback: updated %d accounts for list %d", updated, list_id)
    except Exception:
        logger.exception("Salesforce writeback failed for list %d", list_id)

    # Slack notification for list completion
    try:
        from services.notifications import send_slack_notification
        from database import get_integration as _get_integ
        slack = await _get_integ(user_id, "slack")
        if slack:
            settings = get_settings()
            await send_slack_notification(slack["access_token"], "list_complete", {
                "list_name": final.get("name", f"List {list_id}"),
                "total_accounts": final.get("total_accounts", 0),
                "completed_accounts": final.get("completed_accounts", 0),
                "failed_accounts": failed_count,
                "list_url": f"{settings.app_url}/lists/{list_id}",
            })
    except Exception:
        logger.exception("Slack notification failed for list %d", list_id)

    # Automation rules engine (runs in background to avoid blocking webhooks)
    try:
        from services.automation import evaluate_rules
        from api.tasks import create_tracked_task
        all_accounts_for_rules = await get_list_accounts(list_id)
        completed_for_rules = [
            a for a in all_accounts_for_rules if a.get("status") == "completed"
        ]
        if completed_for_rules:
            create_tracked_task(
                evaluate_rules(user_id, "list_complete", {
                    "list_id": list_id,
                    "accounts": completed_for_rules,
                }),
                name=f"automation-{list_id}",
            )
    except Exception:
        logger.exception("Automation rules failed for list %d", list_id)

    # Fire webhook for list completion
    await _deliver_webhook(user_id, list_id, f"list_{final['status']}", None, None)


async def run_batch_write_sequences(list_id: int, user_id: int, account_ids: list[int] | None = None):
    """Generate outreach sequences for completed accounts in a list."""
    from database import (
        update_list_account_outreach, save_outreach_draft,
        get_list_accounts as _get_accts, get_document,
    )
    from services.instances import writing_service

    all_accounts = await _get_accts(list_id, limit=10000)
    if account_ids:
        accounts = [a for a in all_accounts if a["id"] in account_ids and a.get("status") == "completed" and a.get("document_id")]
    else:
        accounts = [a for a in all_accounts if a.get("status") == "completed" and a.get("document_id")]

    user = await get_user_by_id(user_id)
    if not user:
        return

    semaphore = asyncio.Semaphore(5)

    async def process(account: dict):
        async with semaphore:
            account_id = account["id"]
            await update_list_account_outreach(account_id, "pending")
            try:
                doc = await get_document(account["document_id"], user_id)
                if not doc:
                    await update_list_account_outreach(account_id, "failed")
                    return
                emails = await writing_service.generate_email_sequence(
                    document=doc,
                    product_context=user.get("product_context", ""),
                )
                await save_outreach_draft(account["document_id"], user_id, {"emails": emails})
                await update_list_account_outreach(account_id, "completed")
            except Exception as e:
                logger.exception("Write sequence failed for account %s", account_id)
                await update_list_account_outreach(account_id, "failed")

    BATCH_SIZE = 20
    for batch_start in range(0, len(accounts), BATCH_SIZE):
        batch = accounts[batch_start:batch_start + BATCH_SIZE]
        await asyncio.gather(*(process(a) for a in batch), return_exceptions=True)


async def run_batch_enrich_contacts(list_id: int, user_id: int, account_ids: list[int] | None = None):
    """Stub: batch enrich contacts for accounts in a list.

    Currently a no-op since no enrichment provider is configured.
    When a provider is integrated, only the inner processing logic needs to change.
    Raises RuntimeError so the calling route can return an appropriate message.
    """
    raise RuntimeError("Contact enrichment provider not yet configured")


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
