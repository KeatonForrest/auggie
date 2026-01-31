"""Durable task queue backed by PostgreSQL."""

import json
import logging
from typing import Optional

import db._pool as _db

logger = logging.getLogger(__name__)


async def enqueue_many(task_type: str, payloads: list[dict]) -> int:
    """Bulk-insert tasks. Returns count inserted."""
    if not payloads:
        return 0
    async with _db._pool.acquire() as conn:
        await conn.executemany(
            "INSERT INTO task_queue (task_type, payload) VALUES ($1, $2::jsonb)",
            [(task_type, json.dumps(p)) for p in payloads],
        )
        return len(payloads)


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


async def fail(task_id: int, error: str) -> bool:
    """Mark a task as failed. If attempts < max_attempts, requeue as pending.

    Returns True if retries are exhausted (terminal failure).
    """
    async with _db._pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE task_queue
            SET status = CASE WHEN attempts < max_attempts THEN 'pending' ELSE 'failed' END,
                error = $2,
                completed_at = CASE WHEN attempts >= max_attempts THEN now() ELSE NULL END,
                started_at = NULL,
                claimed_by = NULL
            WHERE id = $1
            RETURNING (attempts >= max_attempts) AS exhausted
            """,
            task_id, error[:2000] if error else None,
        )
        return bool(row and row["exhausted"])


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

        # Clean up finalization markers older than 24 hours
        await conn.execute(
            """
            DELETE FROM task_queue
            WHERE task_type LIKE '_finalize_%'
              AND completed_at < now() - interval '24 hours'
            """
        )

        return count


async def check_no_pending_siblings(job_key: str, job_value: str, lock_id: int) -> bool:
    """Atomically check whether all sibling tasks are terminal and claim finalization.

    Uses pg_advisory_xact_lock to serialize concurrent children. Inside the
    locked transaction, inserts a one-off "finalize_<key>_<id>" task as a
    claim marker. If the marker already exists, another child already won —
    return False. Otherwise, if count=0, return True.

    This guarantees exactly-once finalization even when two children finish
    at the same instant.
    """
    LOCK_NAMESPACE = 737_000
    marker_type = f"_finalize_{job_key}_{job_value}"
    async with _db._pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "SELECT pg_advisory_xact_lock($1, $2)",
                LOCK_NAMESPACE, lock_id,
            )
            # Check if another child already claimed finalization
            existing = await conn.fetchrow(
                "SELECT id FROM task_queue WHERE task_type = $1 LIMIT 1",
                marker_type,
            )
            if existing:
                return False

            row = await conn.fetchrow(
                """
                SELECT count(*) AS cnt FROM task_queue
                WHERE payload->>$1 = $2
                  AND status NOT IN ('completed', 'failed')
                """,
                job_key, job_value,
            )
            if row["cnt"] != 0:
                return False

            # Claim finalization by inserting a marker (immediately completed)
            await conn.execute(
                """
                INSERT INTO task_queue (task_type, payload, status, completed_at)
                VALUES ($1, '{}'::jsonb, 'completed', now())
                """,
                marker_type,
            )
            return True


async def get_queue_stats() -> dict[str, int]:
    """Return task counts grouped by status."""
    async with _db._pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT status, count(*)::int AS cnt FROM task_queue WHERE task_type NOT LIKE '_finalize_%' GROUP BY status"
        )
        return {row["status"]: row["cnt"] for row in rows}
