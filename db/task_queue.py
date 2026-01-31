"""Durable task queue backed by PostgreSQL."""

import json
import logging
from typing import Optional

import db._pool as _db

logger = logging.getLogger(__name__)


async def enqueue(task_type: str, payload: dict) -> int:
    """Insert a task into the queue. Returns the task ID."""
    async with _db._pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO task_queue (task_type, payload)
            VALUES ($1, $2::jsonb)
            RETURNING id
            """,
            task_type, json.dumps(payload),
        )
        return row["id"]


async def claim_next(worker_id: str) -> Optional[dict]:
    """Claim the next pending task using SELECT FOR UPDATE SKIP LOCKED.

    Returns the task record or None if nothing is available.
    """
    async with _db._pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE task_queue
            SET status = 'running',
                started_at = now(),
                attempts = attempts + 1,
                claimed_by = $1
            WHERE id = (
                SELECT id FROM task_queue
                WHERE status = 'pending' AND attempts < max_attempts
                ORDER BY created_at
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            RETURNING *
            """,
            worker_id,
        )
        if not row:
            return None
        result = dict(row)
        if isinstance(result["payload"], str):
            result["payload"] = json.loads(result["payload"])
        return result


async def complete(task_id: int) -> None:
    """Mark a task as completed."""
    async with _db._pool.acquire() as conn:
        await conn.execute(
            "UPDATE task_queue SET status = 'completed', completed_at = now() WHERE id = $1",
            task_id,
        )


async def fail(task_id: int, error: str) -> None:
    """Mark a task as failed. If attempts < max_attempts, requeue as pending."""
    async with _db._pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE task_queue
            SET status = CASE WHEN attempts < max_attempts THEN 'pending' ELSE 'failed' END,
                error = $2,
                completed_at = CASE WHEN attempts >= max_attempts THEN now() ELSE NULL END,
                started_at = NULL,
                claimed_by = NULL
            WHERE id = $1
            """,
            task_id, error[:2000] if error else None,
        )


async def requeue_stale(timeout_minutes: int = 15) -> int:
    """Requeue tasks stuck in 'running' state beyond the timeout.

    Returns the number of tasks requeued.
    """
    async with _db._pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE task_queue
            SET status = 'pending', started_at = NULL, claimed_by = NULL
            WHERE status = 'running'
              AND started_at < now() - make_interval(mins := $1)
              AND attempts < max_attempts
            """,
            timeout_minutes,
        )
        # result is like "UPDATE N"
        count = int(result.split()[-1])
        if count:
            logger.info("Requeued %d stale tasks", count)
        return count
