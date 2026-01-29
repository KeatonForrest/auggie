"""Tracked asyncio task creation with exception logging."""

import asyncio
import logging

_logger = logging.getLogger("background_tasks")


def create_tracked_task(coro, *, name: str = None):
    """Create an asyncio task with exception logging on completion."""
    task = asyncio.create_task(coro, name=name)

    def _done_callback(t):
        if t.cancelled():
            return
        exc = t.exception()
        if exc:
            _logger.error("Background task %s failed: %s", t.get_name(), exc, exc_info=exc)

    task.add_done_callback(_done_callback)
    return task
