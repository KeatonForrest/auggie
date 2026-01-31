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

WORKER_ID = f"worker-{uuid.uuid4().hex[:8]}"
POLL_INTERVAL = 2  # seconds
STALE_CHECK_INTERVAL = 60  # seconds
MAX_CONCURRENT = 10

_shutdown = asyncio.Event()


def _handle_signal():
    logger.info("Received shutdown signal, draining…")
    _shutdown.set()


async def _dispatch(task: dict) -> None:
    """Route a claimed task to the appropriate job function."""
    from db import task_queue
    from api.jobs import run_research_job, run_list_analysis, run_bulk_job, run_batch_write_sequences, run_retry_account
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
        elif task_type == "batch_write":
            await run_batch_write_sequences(**payload)
        elif task_type == "automation":
            await evaluate_rules(payload["user_id"], payload["trigger_event"], payload["context"])
        else:
            raise ValueError(f"Unknown task type: {task_type}")

        await task_queue.complete(task_id)
        logger.info("Task %d (%s) completed", task_id, task_type)

    except Exception as e:
        logger.error("Task %d (%s) failed: %s", task_id, task_type, e, exc_info=True)
        await task_queue.fail(task_id, str(e)[:2000])


async def _poll_loop(semaphore: asyncio.Semaphore) -> None:
    """Continuously claim and dispatch tasks."""
    from db import task_queue

    stale_counter = 0

    while not _shutdown.is_set():
        # Periodically requeue stale tasks
        stale_counter += POLL_INTERVAL
        if stale_counter >= STALE_CHECK_INTERVAL:
            stale_counter = 0
            try:
                await task_queue.requeue_stale()
            except Exception as e:
                logger.warning("Stale requeue failed: %s", e)

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
