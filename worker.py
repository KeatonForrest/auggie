"""Polling worker process for the durable task queue.

Usage:
    python worker.py
"""

import asyncio
import logging
import os
import signal
import uuid

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [worker] %(message)s",
)
logger = logging.getLogger(__name__)

from config import get_settings

WORKER_ID = f"worker-{uuid.uuid4().hex[:8]}"
STALE_CHECK_INTERVAL = 60  # seconds
WATCHLIST_CHECK_INTERVAL = 60  # seconds

_settings = get_settings()
POLL_INTERVAL = _settings.worker_poll_interval
MAX_CONCURRENT = _settings.worker_concurrency

_shutdown = asyncio.Event()


def _handle_signal():
    logger.info("Received shutdown signal, draining…")
    _shutdown.set()


async def _dispatch(task: dict) -> None:
    """Route a claimed task to the appropriate job function."""
    from db import task_queue
    from api.jobs import run_research_job, run_list_analysis, run_bulk_job, run_batch_write_sequences, run_batch_enrich, run_retry_account, run_bulk_item, run_list_item, run_watchlist_item
    from services.automation import evaluate_rules

    task_id = task["id"]
    task_type = task["task_type"]
    payload = task["payload"]

    try:
        if task_type == "research":
            await run_research_job(**payload)
        elif task_type == "retry":
            await run_retry_account(**payload)
        elif task_type == "list_analysis":
            await run_list_analysis(**payload)
        elif task_type == "bulk":
            await run_bulk_job(**payload)
        elif task_type == "bulk_item":
            await run_bulk_item(**payload)
        elif task_type == "list_item":
            await run_list_item(**payload)
        elif task_type == "batch_enrich":
            await run_batch_enrich(**payload)
        elif task_type == "batch_write":
            await run_batch_write_sequences(**payload)
        elif task_type == "watchlist_item":
            await run_watchlist_item(**payload)
        elif task_type == "automation":
            await evaluate_rules(payload["user_id"], payload["trigger_event"], payload["context"])
        else:
            raise ValueError(f"Unknown task type: {task_type}")

        await task_queue.complete(task_id)
        logger.info("Task %d (%s) completed", task_id, task_type)

    except Exception as e:
        logger.error("Task %d (%s) failed: %s", task_id, task_type, e, exc_info=True)
        exhausted = await task_queue.fail(task_id, str(e)[:2000])
        if exhausted:
            # Refund credit for research jobs whose retries are fully exhausted
            if task_type == "research" and not payload.get("is_admin"):
                from database import refund_credit
                await refund_credit(payload["user_id"])
            try:
                from services.notifications import send_task_failure_alert
                await send_task_failure_alert(task_id, task_type, str(e)[:2000])
            except Exception:
                logger.exception("Failed to send failure alert for task %d", task_id)


async def _enqueue_due_watchlist_items() -> None:
    """Claim due watchlist items and enqueue them as tasks."""
    from db.watchlist import claim_due_items
    from db.task_queue import enqueue

    items = await claim_due_items()
    for item in items:
        await enqueue("watchlist_item", {
            "watchlist_item_id": item["id"],
            "user_id": item["user_id"],
            "company_url": item["company_url"],
            "schedule": item["schedule"],
            "last_document_id": item["last_document_id"],
        })
    if items:
        logger.info("Watchlist scheduler: enqueued %d due items", len(items))


async def _poll_loop(semaphore: asyncio.Semaphore) -> None:
    """Continuously claim and dispatch tasks."""
    from db import task_queue

    stale_counter = 0
    watchlist_counter = 0

    while not _shutdown.is_set():
        # Periodically requeue stale tasks
        stale_counter += POLL_INTERVAL
        if stale_counter >= STALE_CHECK_INTERVAL:
            stale_counter = 0
            try:
                await task_queue.requeue_stale()
            except Exception as e:
                logger.warning("Stale requeue failed: %s", e)

        # Periodically enqueue due watchlist items
        watchlist_counter += POLL_INTERVAL
        if watchlist_counter >= WATCHLIST_CHECK_INTERVAL:
            watchlist_counter = 0
            try:
                await _enqueue_due_watchlist_items()
            except Exception as e:
                logger.warning("Watchlist scheduler failed: %s", e)

        # Try to claim a task
        await semaphore.acquire()
        try:
            task = await task_queue.claim_next(WORKER_ID)
        except Exception as e:
            semaphore.release()
            logger.error("Failed to claim task: %s", e)
            await asyncio.sleep(POLL_INTERVAL)
            continue

        if task is None:
            semaphore.release()
            await asyncio.sleep(POLL_INTERVAL)
            continue

        logger.info("Claimed task %d (%s)", task["id"], task["task_type"])

        # Run dispatch in background so we can keep polling
        async def _run(t):
            try:
                await _dispatch(t)
            finally:
                semaphore.release()

        asyncio.create_task(_run(task))


async def main():
    from db._pool import init_database, close_database

    logger.info("Starting worker %s (concurrency=%d)", WORKER_ID, MAX_CONCURRENT)
    await init_database()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal)

    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    try:
        await _poll_loop(semaphore)
    finally:
        # Wait for in-flight tasks to finish
        logger.info("Waiting for in-flight tasks to complete…")
        for _ in range(MAX_CONCURRENT):
            await semaphore.acquire()
        await close_database()
        logger.info("Worker shut down cleanly")


if __name__ == "__main__":
    asyncio.run(main())
