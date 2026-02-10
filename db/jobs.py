"""Research job database operations."""

from typing import Optional

import db._pool as _db


async def _use_credit_conn(conn, user_id: int, cents: int = 100) -> bool:
    """Deduct credits within an existing connection/transaction."""
    row = await conn.fetchrow(
        """
        UPDATE organizations
        SET bonus_credits = bonus_credits - $2
        WHERE id = (SELECT org_id FROM users WHERE id = $1) AND bonus_credits >= $2
        RETURNING bonus_credits
        """,
        user_id, cents,
    )
    return row is not None


async def _insert_job(conn, user_id: int, api_key_id: int | None, company_url: str) -> dict:
    """Insert a research job within an existing connection/transaction."""
    row = await conn.fetchrow(
        """
        INSERT INTO research_jobs (user_id, api_key_id, company_url)
        VALUES ($1, $2, $3)
        RETURNING *
        """,
        user_id, api_key_id, company_url,
    )
    return dict(row)


async def create_job_with_credit(
    user_id: int,
    api_key_id: int | None,
    company_url: str,
    cents: int = 100,
) -> dict:
    """Atomically deduct credit and create a research job in one transaction.

    Returns the job record. Raises ValueError if insufficient credits.
    """
    async with _db._pool.acquire() as conn:
        async with conn.transaction():
            ok = await _use_credit_conn(conn, user_id, cents)
            if not ok:
                raise ValueError("Insufficient credits")
            job = await _insert_job(conn, user_id, api_key_id, company_url)
    # Invalidate usage cache after credit deduction
    from db.users import _invalidate_usage_cache
    _invalidate_usage_cache(user_id)
    return job



async def create_research_job(user_id: int, api_key_id: int | None, company_url: str) -> dict:
    """Create a new research job. Returns the job record."""
    async with _db._pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO research_jobs (user_id, api_key_id, company_url)
            VALUES ($1, $2, $3)
            RETURNING *
            """,
            user_id, api_key_id, company_url
        )
        return dict(row)


async def get_research_job(job_id: int, user_id: int) -> Optional[dict]:
    """Get a research job by ID (scoped to user)."""
    async with _db._pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM research_jobs WHERE id = $1 AND user_id = $2",
            job_id, user_id
        )
        return dict(row) if row else None


async def update_job_status(
    job_id: int,
    status: str,
    document_id: int = None,
    error_message: str = None,
) -> None:
    """Update a job's status and optional result fields."""
    async with _db._pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE research_jobs
            SET status = $2, document_id = $3, error_message = $4,
                completed_at = CASE WHEN $2 IN ('completed', 'failed') THEN NOW() ELSE completed_at END
            WHERE id = $1
            """,
            job_id, status, document_id, error_message
        )


async def update_job_progress(job_id: int, progress: str) -> None:
    """Update a job's progress stage (e.g. 'scraping', 'analyzing')."""
    async with _db._pool.acquire() as conn:
        await conn.execute(
            "UPDATE research_jobs SET progress = $2 WHERE id = $1",
            job_id, progress
        )


async def list_user_jobs(user_id: int, limit: int = 20, offset: int = 0) -> list[dict]:
    """List recent research jobs for a user."""
    async with _db._pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, company_url, status, document_id, error_message, created_at, completed_at
            FROM research_jobs
            WHERE user_id = $1
            ORDER BY created_at DESC
            LIMIT $2 OFFSET $3
            """,
            user_id, limit, offset
        )
        return [dict(row) for row in rows]
