"""Background job runner for async research."""

import asyncio
import logging

import httpx

from database import (
    get_user_by_id, save_document, get_document,
    record_api_usage, update_job_status, update_job_progress, get_user_webhook,
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


async def _run_research_pipeline(user_id: int, company_url: str, job_id: int | None = None) -> int:
    """Execute the core research pipeline: scrape, analyze, save.

    Returns the document ID on success. Raises on failure.
    """
    user = await get_user_by_id(user_id)
    if not user:
        raise RuntimeError("User not found")

    if job_id:
        await update_job_progress(job_id, "scraping")
    scraped_content = await firecrawl_service.scrape_company(company_url)

    if job_id:
        await update_job_progress(job_id, "analyzing")
    tech_by_domain = await wappalyzer_service.analyze_multiple_domains(
        main_url=company_url,
        main_html=scraped_content.homepage_html,
    )

    if job_id:
        await update_job_progress(job_id, "enriching")
    retrieved_materials = await collect_enrichment_data(
        scraped_content, company_url, user_id,
    )

    if job_id:
        await update_job_progress(job_id, "generating")
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
        product_type=user.get("product_type", "saas"),
    )

    doc_id = await save_document(document, user_id=user_id)
    return doc_id


async def run_research_job(
    job_id: int, user_id: int, api_key_id: int | None, company_url: str,
    *, is_admin: bool = False,
):
    """Execute the research pipeline in the background and update job status.

    Credit is reserved before this function is called. On failure this function
    updates the job row and fires the webhook, then re-raises so the task queue
    can track retries. The caller is responsible for refunding credits once
    retries are exhausted.
    """
    try:
        doc_id = await _run_research_pipeline(user_id, company_url, job_id=job_id)

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
        error_msg = str(e)[:500]
        await update_job_status(job_id, "failed", error_message=error_msg)
        await _deliver_webhook(user_id, job_id, "failed", None, error_msg)
        raise


async def _fan_out(task_type: str, items: list[dict], shared_payload: dict, label: str) -> None:
    """Enqueue one child task per item with shared context fields.

    Each item dict is merged with shared_payload plus an account_index key.
    Inserts in chunks of 500 via bulk enqueue to avoid serial round-trips.
    """
    from db.task_queue import enqueue_many

    CHUNK = 500
    for start in range(0, len(items), CHUNK):
        chunk = items[start:start + CHUNK]
        payloads = [{**shared_payload, **item, "account_index": start + i} for i, item in enumerate(chunk)]
        await enqueue_many(task_type, payloads)
    logger.info("%s: enqueued %d child tasks", label, len(items))


async def run_bulk_job(bulk_job_id: int, user_id: int, api_key_id: int, is_admin: bool = False):
    """Fan out: enqueue one bulk_item task per account, then return immediately."""
    items = await get_bulk_job_items(bulk_job_id)
    await _fan_out("bulk_item", [
        {"bulk_job_id": bulk_job_id, "item_id": it["id"], "company_url": it["company_url"]}
        for it in items
    ], {"user_id": user_id, "api_key_id": api_key_id, "is_admin": is_admin},
        f"Bulk job {bulk_job_id}")


async def run_bulk_item(
    bulk_job_id: int, item_id: int, company_url: str,
    user_id: int, api_key_id: int, is_admin: bool = False,
    account_index: int = 0,
):
    """Process a single bulk job item, then check if we're the last child."""
    from db.task_queue import check_no_pending_siblings

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

    # Check if all siblings are done — if so, finalize parent (advisory-locked)
    all_done = await check_no_pending_siblings("bulk_job_id", str(bulk_job_id), bulk_job_id)
    if all_done:
        logger.info("Bulk job %d: all children done, finalizing", bulk_job_id)
        final = await finalize_bulk_job(bulk_job_id)
        failed_count = final["failed_items"]
        if failed_count > 0 and not is_admin:
            await refund_credit(user_id, cents=failed_count * 100)
        await _deliver_webhook(user_id, bulk_job_id, f"bulk_{final['status']}", None, None)


async def run_list_analysis(list_id: int, user_id: int, api_key_id: int | None = None, is_admin: bool = False):
    """Fan out: enqueue one list_item task per pending account, then return immediately."""
    accounts = await get_pending_list_accounts(list_id)
    await _fan_out("list_item", [
        {"list_id": list_id, "account_id": a["id"], "company_url": a["company_url"]}
        for a in accounts
    ], {"user_id": user_id, "api_key_id": api_key_id, "is_admin": is_admin},
        f"List {list_id}")


async def run_list_item(
    list_id: int, account_id: int, company_url: str,
    user_id: int, api_key_id: int | None = None, is_admin: bool = False,
    account_index: int = 0,
):
    """Process a single list account, then check if we're the last child."""
    from db.task_queue import enqueue, check_no_pending_siblings

    job = await create_research_job(user_id, api_key_id, company_url)
    await update_list_account(account_id, "processing", research_job_id=job["id"])

    try:
        doc_id = await _run_research_pipeline(user_id, company_url)

        if api_key_id is not None:
            await record_api_usage(api_key_id, "/v1/research", 1)
        await update_job_status(job["id"], "completed", document_id=doc_id)

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
            await enqueue("automation", {
                "user_id": user_id,
                "trigger_event": "account_scored",
                "context": {"list_id": list_id, "accounts": [scored_account]},
            })
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

    # Check if all siblings are done — if so, finalize parent (advisory-locked)
    all_done = await check_no_pending_siblings("list_id", str(list_id), list_id)
    if all_done:
        logger.info("List %d: all children done, finalizing", list_id)
        await _finalize_list_parent(list_id, user_id, is_admin)


async def _finalize_list_parent(list_id: int, user_id: int, is_admin: bool):
    """Run all list finalization: status, refunds, CRM writeback, Slack, automation, webhook."""
    final = await finalize_list(list_id)
    failed_count = final["failed_accounts"]
    if failed_count > 0 and not is_admin:
        await refund_credit(user_id, cents=failed_count * 100)

    # HubSpot writeback
    try:
        source = await get_list_source(list_id)
        if source and source.get("provider") == "hubspot":
            from services.hubspot import write_list_scores_to_hubspot
            all_accounts = await get_list_accounts(list_id)
            updated = await write_list_scores_to_hubspot(user_id, source, all_accounts)
            logger.info("HubSpot writeback: updated %d companies for list %d", updated, list_id)
    except Exception:
        logger.exception("HubSpot writeback failed for list %d", list_id)

    # Salesforce writeback
    try:
        source = await get_list_source(list_id)
        if source and source.get("provider") == "salesforce":
            from services.salesforce import write_list_scores_to_salesforce
            all_accounts = await get_list_accounts(list_id)
            updated = await write_list_scores_to_salesforce(user_id, source, all_accounts)
            logger.info("Salesforce writeback: updated %d accounts for list %d", updated, list_id)
    except Exception:
        logger.exception("Salesforce writeback failed for list %d", list_id)

    # Slack notification
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

    # Automation rules
    try:
        from db.task_queue import enqueue
        all_accounts_for_rules = await get_list_accounts(list_id)
        completed_for_rules = [
            a for a in all_accounts_for_rules if a.get("status") == "completed"
        ]
        if completed_for_rules:
            await enqueue("automation", {
                "user_id": user_id,
                "trigger_event": "list_complete",
                "context": {"list_id": list_id, "accounts": completed_for_rules},
            })
    except Exception:
        logger.exception("Automation rules failed for list %d", list_id)

    # Webhook
    await _deliver_webhook(user_id, list_id, f"list_{final['status']}", None, None)


async def run_retry_account(user_id: int, account_id: int, company_url: str, job_id: int, is_admin: bool = False):
    """Retry a single list account: run pipeline + update list_account row."""
    try:
        doc_id = await _run_research_pipeline(user_id, company_url, job_id=job_id)
        await update_job_status(job_id, "completed", document_id=doc_id)
        doc = await get_document(doc_id, user_id)
        from database import update_list_account
        await update_list_account(
            account_id, "completed",
            document_id=doc_id,
            research_job_id=job_id,
            pain_score=doc.pain_score,
            fit_score=doc.fit_score,
            timing_score=doc.timing_score,
            composite_score=doc.opportunity_score,
            company_name=doc.company_name,
        )
    except Exception as e:
        logger.exception("Retry account %s failed", account_id)
        if not is_admin:
            await refund_credit(user_id)
        error_msg = str(e)[:500]
        await update_job_status(job_id, "failed", error_message=error_msg)
        from database import update_list_account
        await update_list_account(account_id, "failed", research_job_id=job_id, error_message=error_msg)


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
                    product_type=user.get("product_type", "saas"),
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
