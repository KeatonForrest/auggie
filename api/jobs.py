"""Background job runner for async research."""

import asyncio
import logging
import time

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
from urllib.parse import urlparse as _urlparse
from services.collect import collect_enrichment_data
from services.instances import (
    firecrawl_service, claude_service, tech_detection_service,
    dns_analyzer, ssl_analyzer, job_parser, pain_engine,
)
from models import SignalBundle, SellerContext
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

    pipeline_start = time.monotonic()

    if job_id:
        await update_job_progress(job_id, "scraping")
    t0 = time.monotonic()
    scraped_content = await firecrawl_service.scrape_company(company_url)
    logger.info("[pipeline %s] scraping: %.1fs", company_url, time.monotonic() - t0)

    if job_id:
        await update_job_progress(job_id, "analyzing")
    # Extract domain for DNS/SSL analysis
    _parsed = _urlparse(company_url if company_url.startswith("http") else f"https://{company_url}")
    domain = _parsed.netloc.replace("www.", "") or _parsed.path.split("/")[0].replace("www.", "")
    full_main_url = f"https://{domain}"

    t0 = time.monotonic()
    tech_by_domain, dns_profile, ssl_profile = await asyncio.gather(
        tech_detection_service.analyze_multiple_domains(main_url=company_url, main_html=scraped_content.homepage_html),
        dns_analyzer.analyze(domain),
        ssl_analyzer.analyze(domain),
    )
    logger.info("[pipeline %s] tech+dns+ssl: %.1fs", domain, time.monotonic() - t0)

    # Phase 3: security headers, robots, job signals
    security_posture = tech_detection_service.score_security_headers(
        tech_detection_service.get_last_main_headers()
    )
    robots_text = tech_detection_service.get_robots_text(full_main_url)
    robots_signals = tech_detection_service.extract_robots_signals(robots_text) if robots_text else None
    job_signals = job_parser.parse(scraped_content.job_postings) if scraped_content.job_postings else None

    # Phase 4: pain inference
    t0 = time.monotonic()
    bundle = SignalBundle(
        domain=domain, tech_by_domain=tech_by_domain,
        dns_profile=dns_profile, ssl_profile=ssl_profile,
        security_posture=security_posture, robots_signals=robots_signals,
        job_signals=job_signals,
    )
    seller_context = SellerContext(
        product_type=user.get("product_type", "saas"),
        problems_solved=user.get("problems_solved", ""),
    )
    pain_inferences = pain_engine.evaluate(bundle, seller=seller_context,
                                           seller_product_context=user.get("product_context", ""))
    pain_ms = (time.monotonic() - t0) * 1000
    logger.info("[pipeline %s] pain inference: %.0fms (%d signals)", domain, pain_ms, len(pain_inferences))

    if job_id:
        await update_job_progress(job_id, "enriching")
    t0 = time.monotonic()
    retrieved_materials = await collect_enrichment_data(
        scraped_content, company_url, user_id,
    )
    logger.info("[pipeline %s] enrichment: %.1fs", domain, time.monotonic() - t0)

    if job_id:
        await update_job_progress(job_id, "generating")
    t0 = time.monotonic()
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
        custom_signals=user.get("custom_signals", ""),
        solution_motion=user.get("solution_motion", "horizontal"),
        seller_product_category=user.get("seller_product_category", ""),
        dns_profile=dns_profile,
        ssl_profile=ssl_profile,
        security_posture=security_posture,
        robots_signals=robots_signals,
        job_signals=job_signals,
        pain_inferences=pain_inferences,
    )
    logger.info("[pipeline %s] claude generation: %.1fs", domain, time.monotonic() - t0)

    t0 = time.monotonic()
    doc_id = await save_document(document, user_id=user_id)

    # Phase 5: persist tech signals and pain inferences
    try:
        from db.tech_signals import save_tech_signals, save_pain_inferences
        await save_tech_signals(doc_id, tech_by_domain, dns_profile, ssl_profile, job_signals)
        await save_pain_inferences(doc_id, pain_inferences)
    except Exception:
        logger.warning("Failed to save tech signals/pain inferences for doc %s", doc_id, exc_info=True)
    logger.info("[pipeline %s] persistence: %.1fs", domain, time.monotonic() - t0)
    logger.info("[pipeline %s] TOTAL: %.1fs", domain, time.monotonic() - pipeline_start)

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

        # Slack / Teams notifications
        try:
            from services.notifications import send_slack_notification, send_teams_notification
            from database import get_integration as _get_integ
            from db.documents import get_document_slug_path
            slack = await _get_integ(user_id, "slack")
            teams = await _get_integ(user_id, "teams")
            if slack or teams:
                doc = await get_document(doc_id, user_id)
                settings = get_settings()
                slug_path = await get_document_slug_path(doc_id, user_id)
                doc_url = f"{settings.app_url}{slug_path}" if slug_path else f"{settings.app_url}/document/{doc_id}"
                notify_data = {
                    "company_name": doc.company_name if doc else company_url,
                    "company_url": company_url,
                    "pain_score": doc.pain_score if doc else None,
                    "composite_score": doc.opportunity_score if doc else None,
                    "doc_url": doc_url,
                }
                if slack:
                    await send_slack_notification(slack["access_token"], "research_complete", notify_data)
                    if doc and doc.pain_score is not None and doc.pain_score >= 80:
                        await send_slack_notification(slack["access_token"], "high_pain_alert", notify_data)
                if teams:
                    await send_teams_notification(teams["access_token"], "research_complete", notify_data)
                    if doc and doc.pain_score is not None and doc.pain_score >= 80:
                        await send_teams_notification(teams["access_token"], "high_pain_alert", notify_data)
        except Exception:
            logger.exception("Notification failed for job %s", job_id)

        # Fire webhook
        await _deliver_webhook(user_id, "research.completed", {
            "job_id": job_id, "document_id": doc_id, "company_url": company_url,
        })

    except Exception as e:
        logger.exception("Research job %s failed", job_id)
        error_msg = str(e)[:500]
        await update_job_status(job_id, "failed", error_message=error_msg)
        await _deliver_webhook(user_id, "research.failed", {
            "job_id": job_id, "error": error_msg, "company_url": company_url,
        })
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
        event_type = "bulk.completed" if final["status"] in ("completed", "partial_failure") else "bulk.failed"
        await _deliver_webhook(user_id, event_type, {
            "bulk_job_id": bulk_job_id, "status": final["status"],
            "completed_items": final["completed_items"], "failed_items": final["failed_items"],
        })


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

    # Slack / Teams notification
    try:
        from services.notifications import send_slack_notification, send_teams_notification
        from database import get_integration as _get_integ
        slack = await _get_integ(user_id, "slack")
        teams = await _get_integ(user_id, "teams")
        if slack or teams:
            settings = get_settings()
            list_notify_data = {
                "list_name": final.get("name", f"List {list_id}"),
                "total_accounts": final.get("total_accounts", 0),
                "completed_accounts": final.get("completed_accounts", 0),
                "failed_accounts": failed_count,
                "list_url": f"{settings.app_url}/lists/{list_id}",
            }
            if slack:
                await send_slack_notification(slack["access_token"], "list_complete", list_notify_data)
            if teams:
                await send_teams_notification(teams["access_token"], "list_complete", list_notify_data)
    except Exception:
        logger.exception("Notification failed for list %d", list_id)

    # Automation rules
    try:
        from db.task_queue import enqueue
        all_accounts_for_rules, _ = await get_list_accounts(list_id)
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
    event_type = "list.analyzed" if final["status"] in ("completed", "partial_failure") else "list.failed"
    await _deliver_webhook(user_id, event_type, {
        "list_id": list_id, "status": final["status"],
        "total_accounts": final.get("total_accounts", 0),
        "analyzed_accounts": final.get("analyzed_accounts", 0),
        "failed_accounts": final["failed_accounts"],
    })


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

    all_accounts, _ = await _get_accts(list_id, limit=10000)
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
                # Retrieve relevant materials for this prospect
                materials = ""
                try:
                    from services.collect import _get_retrieval_service
                    retrieval = _get_retrieval_service()
                    if retrieval:
                        materials = await retrieval.get_relevant_context(
                            user_id=user_id,
                            company_name=doc.company_name,
                            company_description=doc.company_overview[:500] if doc.company_overview else "",
                        ) or ""
                except Exception:
                    pass  # Non-fatal, proceed without materials
                emails, _subject_options = await writing_service.generate_email_sequence(
                    document=doc,
                    product_context=user.get("product_context", ""),
                    product_type=user.get("product_type", "saas"),
                    retrieved_materials=materials,
                    seller_company=user.get("company_name", ""),
                    problems_solved=user.get("problems_solved", ""),
                    custom_signals=user.get("custom_signals", ""),
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


async def run_batch_enrich(list_id: int, user_id: int, account_ids: list[int] | None = None):
    """Enrich contacts for completed accounts in a list using BYOK providers."""
    from database import (
        update_list_account_enrichment, save_enriched_contacts,
        get_list_accounts as _get_accts,
    )
    from services.enrichment import enrich_company_contacts
    from routes._helpers import _build_target_titles

    user = await get_user_by_id(user_id)
    target_titles = _build_target_titles(user) if user else []

    all_accounts, _ = await _get_accts(list_id, limit=10000)
    if account_ids:
        accounts = [a for a in all_accounts if a["id"] in account_ids and a.get("status") == "completed"]
    else:
        accounts = [a for a in all_accounts if a.get("status") == "completed"]

    semaphore = asyncio.Semaphore(5)

    async def process(account: dict):
        async with semaphore:
            account_id = account["id"]
            await update_list_account_enrichment(account_id, "pending")
            try:
                domain = account.get("company_url", "")
                if not domain:
                    await update_list_account_enrichment(account_id, "failed", "No company URL")
                    return

                contacts = await enrich_company_contacts(
                    user_id, domain, company_name=account.get("company_name", ""),
                    person_titles=target_titles,
                )
                if not contacts:
                    await update_list_account_enrichment(account_id, "completed")
                    return

                doc_id = account.get("document_id")
                if doc_id:
                    await save_enriched_contacts(doc_id, user_id, contacts)

                await update_list_account_enrichment(account_id, "completed")
                logger.info("Enriched %d contacts for account %s", len(contacts), account.get("company_name"))
            except Exception as e:
                logger.exception("Enrichment failed for account %s", account_id)
                await update_list_account_enrichment(account_id, "failed", str(e)[:500])

    BATCH_SIZE = 20
    for batch_start in range(0, len(accounts), BATCH_SIZE):
        batch = accounts[batch_start:batch_start + BATCH_SIZE]
        await asyncio.gather(*(process(a) for a in batch), return_exceptions=True)


async def run_watchlist_item(
    watchlist_item_id: int, user_id: int, company_url: str,
    schedule: str, last_document_id: int | None = None,
):
    """Re-research a watched company: deduct credit, run pipeline, record score delta."""
    from db.watchlist import (
        record_score_change, complete_watchlist_run, mark_skipped_no_credits,
    )
    from db.jobs import create_job_with_credit

    # Deduct 1 credit (100 cents)
    try:
        job = await create_job_with_credit(user_id, None, company_url)
    except ValueError:
        logger.info("Watchlist item %d: skipped (no credits)", watchlist_item_id)
        await mark_skipped_no_credits(watchlist_item_id)
        return

    try:
        # Capture old scores
        old_scores: dict = {}
        if last_document_id:
            old_doc = await get_document(last_document_id, user_id)
            if old_doc:
                old_scores = {
                    "opportunity_score": old_doc.opportunity_score,
                    "pain_score": old_doc.pain_score,
                    "fit_score": old_doc.fit_score,
                    "timing_score": old_doc.timing_score,
                }

        # Run pipeline
        doc_id = await _run_research_pipeline(user_id, company_url, job_id=job["id"])
        await update_job_status(job["id"], "completed", document_id=doc_id)

        # Get new scores
        new_doc = await get_document(doc_id, user_id)
        new_scores = {
            "opportunity_score": new_doc.opportunity_score if new_doc else None,
            "pain_score": new_doc.pain_score if new_doc else None,
            "fit_score": new_doc.fit_score if new_doc else None,
            "timing_score": new_doc.timing_score if new_doc else None,
        }

        # Record delta
        change = await record_score_change(
            watchlist_item_id, last_document_id, doc_id, old_scores, new_scores,
        )

        # Update watchlist item
        await complete_watchlist_run(watchlist_item_id, doc_id, schedule)

        # Notify if significant change
        if change.get("is_significant"):
            try:
                from services.notifications import send_slack_notification, send_teams_notification
                from database import get_integration as _get_integ
                from db.documents import get_document_slug_path as _get_slug_path
                slack = await _get_integ(user_id, "slack")
                teams = await _get_integ(user_id, "teams")
                if slack or teams:
                    settings = get_settings()
                    _slug_p = await _get_slug_path(doc_id, user_id)
                    _doc_url = f"{settings.app_url}{_slug_p}" if _slug_p else f"{settings.app_url}/document/{doc_id}"
                    notify_data = {
                        "company_name": new_doc.company_name if new_doc else company_url,
                        "company_url": company_url,
                        "pain_score": new_scores.get("pain_score"),
                        "old_pain_score": old_scores.get("pain_score"),
                        "composite_score": new_scores.get("opportunity_score"),
                        "old_composite_score": old_scores.get("opportunity_score"),
                        "doc_url": _doc_url,
                        "watchlist_url": f"{settings.app_url}/watchlist",
                    }
                    if slack:
                        await send_slack_notification(slack["access_token"], "watchlist_significant_change", notify_data)
                    if teams:
                        await send_teams_notification(teams["access_token"], "watchlist_significant_change", notify_data)
            except Exception:
                logger.exception("Notification failed for watchlist item %s", watchlist_item_id)

    except Exception as e:
        logger.exception("Watchlist item %s failed", watchlist_item_id)
        error_msg = str(e)[:500]
        await update_job_status(job["id"], "failed", error_message=error_msg)
        # Re-schedule despite failure so it tries again next cycle
        await complete_watchlist_run(watchlist_item_id, last_document_id, schedule)
        raise


WEBHOOK_MAX_RETRIES = 5
WEBHOOK_BACKOFF_BASE = 5  # seconds


async def _deliver_webhook(user_id: int, event_type: str, data: dict):
    """Send webhook notification with event envelope and type filtering.

    Builds a structured event envelope, checks event_types subscription,
    signs the full envelope, and delivers with exponential backoff retries.
    """
    webhook = await get_user_webhook(user_id)
    if not webhook:
        return

    # Check event type filtering — if event_types is set and doesn't include this type, skip
    subscribed = webhook.get("event_types")
    if subscribed is not None and event_type not in subscribed:
        return

    from db.webhooks import create_webhook_event
    event = await create_webhook_event(webhook["id"], event_type, data)

    # Build event envelope
    payload = {
        "id": event["id"],
        "type": event_type,
        "created_at": event["created_at"].isoformat() if hasattr(event["created_at"], "isoformat") else str(event["created_at"]),
        "data": data,
    }

    delivery = await create_webhook_delivery(webhook["id"], data.get("job_id"))
    signature = sign_payload(payload, webhook["secret"])

    last_error = None
    last_http_status = None

    for attempt in range(1, WEBHOOK_MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    webhook["url"],
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "X-Webhook-Signature": f"sha256={signature}",
                    },
                )
            last_http_status = resp.status_code

            if resp.status_code < 400:
                await update_delivery_status(
                    delivery["id"], status="success",
                    http_status=resp.status_code, attempts=attempt,
                )
                return

            if 400 <= resp.status_code < 500 and resp.status_code != 429:
                logger.warning("Webhook delivery %s got %s (client error), not retrying", delivery["id"], resp.status_code)
                await update_delivery_status(
                    delivery["id"], status="failed",
                    http_status=resp.status_code, attempts=attempt,
                )
                return

            last_error = f"HTTP {resp.status_code}"
            logger.warning("Webhook delivery %s attempt %d/%d got %s, retrying", delivery["id"], attempt, WEBHOOK_MAX_RETRIES, resp.status_code)

        except Exception as e:
            last_error = str(e)[:500]
            logger.warning("Webhook delivery %s attempt %d/%d failed: %s", delivery["id"], attempt, WEBHOOK_MAX_RETRIES, last_error)

        if attempt < WEBHOOK_MAX_RETRIES:
            backoff = min(WEBHOOK_BACKOFF_BASE ** attempt, 125)
            await asyncio.sleep(backoff)

    logger.error("Webhook delivery %s failed after %d attempts", delivery["id"], WEBHOOK_MAX_RETRIES)
    await update_delivery_status(
        delivery["id"], status="failed",
        http_status=last_http_status,
        error_message=last_error,
        attempts=WEBHOOK_MAX_RETRIES,
    )
