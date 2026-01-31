"""Tracked task creation — enqueues to durable PostgreSQL task queue."""

import asyncio
import logging

from db.task_queue import enqueue

_logger = logging.getLogger("background_tasks")


async def create_tracked_task(task_type: str, payload: dict, *, name: str = None) -> int:
    """Enqueue a task to the durable queue. Returns the queue task ID."""
    task_id = await enqueue(task_type, payload)
    _logger.info("Enqueued task %s (id=%d, name=%s)", task_type, task_id, name)
    return task_id
