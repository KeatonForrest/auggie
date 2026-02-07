"""Bulk job database operations."""

import db._pool as _db


async def create_bulk_job(user_id: int, api_key_id: int, name: str | None, total_items: int, credits_reserved: int) -> dict:
    """Create a new bulk job. Returns the job record."""
    async with _db._pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO bulk_jobs (user_id, api_key_id, name, total_items, credits_reserved)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING *
            """,
            user_id, api_key_id, name, total_items, credits_reserved
        )
        return dict(row)


async def get_bulk_job(bulk_job_id: int, user_id: int) -> dict | None:
    """Get a bulk job by ID (scoped to user)."""
    async with _db._pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM bulk_jobs WHERE id = $1 AND user_id = $2",
            bulk_job_id, user_id
        )
        return dict(row) if row else None


async def list_bulk_jobs(user_id: int, limit: int = 20, offset: int = 0) -> list[dict]:
    """List recent bulk jobs for a user."""
    async with _db._pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, name, status, total_items, completed_items, failed_items,
                   credits_reserved, created_at, completed_at
            FROM bulk_jobs
            WHERE user_id = $1
            ORDER BY created_at DESC
            LIMIT $2 OFFSET $3
            """,
            user_id, limit, offset
        )
        return [dict(row) for row in rows]


async def create_bulk_job_items(bulk_job_id: int, urls: list[str]) -> list[dict]:
    """Batch-insert items for a bulk job. Returns list of item records."""
    async with _db._pool.acquire() as conn:
        await conn.executemany(
            "INSERT INTO bulk_job_items (bulk_job_id, company_url) VALUES ($1, $2)",
            [(bulk_job_id, url) for url in urls],
        )
        rows = await conn.fetch(
            "SELECT * FROM bulk_job_items WHERE bulk_job_id = $1 ORDER BY id",
            bulk_job_id,
        )
        return [dict(row) for row in rows]


async def iter_bulk_job_items(bulk_job_id: int, page_size: int = 500):
    """Async generator that yields bulk job items in pages."""
    last_id = 0
    async with _db._pool.acquire() as conn:
        while True:
            rows = await conn.fetch(
                """SELECT id, bulk_job_id, research_job_id, company_url, status,
                          document_id, error_message, created_at, completed_at
                   FROM bulk_job_items
                   WHERE bulk_job_id = $1 AND id > $2
                   ORDER BY id LIMIT $3""",
                bulk_job_id, last_id, page_size,
            )
            if not rows:
                break
            for row in rows:
                yield dict(row)
            last_id = rows[-1]["id"]


async def get_bulk_job_items(bulk_job_id: int) -> list[dict]:
    """Get all items for a bulk job."""
    return [item async for item in iter_bulk_job_items(bulk_job_id)]


async def update_bulk_job_item(
    item_id: int,
    status: str,
    research_job_id: int | None = None,
    document_id: int | None = None,
    error_message: str | None = None,
) -> None:
    """Update a bulk job item and atomically increment parent counters."""
    async with _db._pool.acquire() as conn:
        async with conn.transaction():
            # Update the item
            await conn.execute(
                """
                UPDATE bulk_job_items
                SET status = $2, research_job_id = $3, document_id = $4,
                    error_message = $5,
                    completed_at = CASE WHEN $2 IN ('completed', 'failed') THEN NOW() ELSE completed_at END
                WHERE id = $1
                """,
                item_id, status, research_job_id, document_id, error_message
            )
            # Increment parent counters
            if status == 'completed':
                await conn.execute(
                    """
                    UPDATE bulk_jobs SET completed_items = completed_items + 1
                    WHERE id = (SELECT bulk_job_id FROM bulk_job_items WHERE id = $1)
                    """,
                    item_id
                )
            elif status == 'failed':
                await conn.execute(
                    """
                    UPDATE bulk_jobs SET failed_items = failed_items + 1
                    WHERE id = (SELECT bulk_job_id FROM bulk_job_items WHERE id = $1)
                    """,
                    item_id
                )


async def finalize_bulk_job(bulk_job_id: int) -> dict:
    """Set final status and completed_at on a bulk job. Returns updated record."""
    async with _db._pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT total_items, completed_items, failed_items FROM bulk_jobs WHERE id = $1 FOR UPDATE",
                bulk_job_id
            )
            if row["failed_items"] == row["total_items"]:
                final_status = "failed"
            elif row["failed_items"] > 0:
                final_status = "partial_failure"
            else:
                final_status = "completed"

            updated = await conn.fetchrow(
                """
                UPDATE bulk_jobs SET status = $2, completed_at = NOW()
                WHERE id = $1
                RETURNING *
                """,
                bulk_job_id, final_status
            )
            return dict(updated)
