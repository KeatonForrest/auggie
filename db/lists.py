"""List database operations."""

import json

import db._pool as _db


async def create_list(user_id: int, api_key_id: int | None, name: str, *, org_id: int | None = None) -> dict:
    """Create a new list (org-scoped). Returns the list record."""
    async with _db._pool.acquire() as conn:
        if org_id is None:
            org_id = await conn.fetchval("SELECT org_id FROM users WHERE id = $1", user_id)
        row = await conn.fetchrow(
            """
            INSERT INTO lists (user_id, api_key_id, name, org_id)
            VALUES ($1, $2, $3, $4)
            RETURNING *
            """,
            user_id, api_key_id, name, org_id
        )
        return dict(row)


async def get_list(list_id: int, user_id: int) -> dict | None:
    """Get a list by ID (scoped to user's org)."""
    async with _db._pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT * FROM lists
            WHERE id = $1 AND org_id = (SELECT org_id FROM users WHERE id = $2)
            """,
            list_id, user_id
        )
        return dict(row) if row else None


async def count_lists(user_id: int) -> int:
    """Count total lists for a user's org."""
    async with _db._pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT COUNT(*) FROM lists WHERE org_id = (SELECT org_id FROM users WHERE id = $1)",
            user_id,
        )


async def list_lists(user_id: int, limit: int = 20, offset: int = 0) -> list[dict]:
    """List recent lists for a user's org (shared)."""
    async with _db._pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, name, status, total_accounts, analyzed_accounts,
                   failed_accounts, credits_reserved, created_at, updated_at
            FROM lists
            WHERE org_id = (SELECT org_id FROM users WHERE id = $1)
            ORDER BY created_at DESC
            LIMIT $2 OFFSET $3
            """,
            user_id, limit, offset
        )
        return [dict(row) for row in rows]


async def delete_list(list_id: int, user_id: int) -> bool:
    """Delete a list and all its accounts (org-scoped). Returns True if deleted."""
    async with _db._pool.acquire() as conn:
        result = await conn.execute(
            """
            DELETE FROM lists
            WHERE id = $1 AND org_id = (SELECT org_id FROM users WHERE id = $2)
            """,
            list_id, user_id
        )
        return result == "DELETE 1"


async def add_list_accounts(list_id: int, company_urls: list[str], source_ids: dict[str, str] | None = None) -> list[dict]:
    """Batch-insert accounts for a list. Updates total_accounts on parent. Returns account records."""
    async with _db._pool.acquire() as conn:
        await conn.executemany(
            "INSERT INTO list_accounts (list_id, company_url, source_id) VALUES ($1, $2, $3)",
            [(list_id, url, (source_ids or {}).get(url)) for url in company_urls],
        )
        await conn.execute(
            "UPDATE lists SET total_accounts = $2, updated_at = NOW() WHERE id = $1",
            list_id, len(company_urls)
        )
        rows = await conn.fetch(
            "SELECT * FROM list_accounts WHERE list_id = $1 ORDER BY id",
            list_id,
        )
        return [dict(row) for row in rows]


async def get_pipeline_counts(list_id: int) -> dict:
    """Return pipeline step counts for a list in a single SQL query."""
    query = """
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE status = 'completed') AS scored,
            COUNT(*) FILTER (WHERE enrichment_status = 'completed') AS enriched,
            COUNT(*) FILTER (WHERE outreach_status = 'completed') AS sequences_written,
            COUNT(*) FILTER (WHERE pushed_to IS NOT NULL AND pushed_to::text != '{}' AND pushed_to::text != 'null') AS pushed,
            COUNT(*) FILTER (WHERE status = 'failed') AS failed
        FROM list_accounts
        WHERE list_id = $1
    """
    async with _db._pool.acquire() as conn:
        row = await conn.fetchrow(query, list_id)
        return dict(row)


async def count_ready_accounts(list_id: int, account_ids: list[int] | None = None) -> int:
    """Count completed accounts that have documents (ready for sequence writing)."""
    if account_ids:
        query = """
            SELECT COUNT(*) FROM list_accounts
            WHERE list_id = $1 AND status = 'completed' AND document_id IS NOT NULL
              AND id = ANY($2)
        """
        async with _db._pool.acquire() as conn:
            return await conn.fetchval(query, list_id, account_ids)
    else:
        query = """
            SELECT COUNT(*) FROM list_accounts
            WHERE list_id = $1 AND status = 'completed' AND document_id IS NOT NULL
        """
        async with _db._pool.acquire() as conn:
            return await conn.fetchval(query, list_id)


async def count_list_accounts(
    list_id: int,
    min_pain: int | None = None,
    min_composite: int | None = None,
) -> int:
    """Count accounts for a list with optional filtering (mirrors get_list_accounts filters)."""
    conditions = ["list_id = $1"]
    params: list = [list_id]
    idx = 2

    if min_pain is not None:
        conditions.append(f"pain_score >= ${idx}")
        params.append(min_pain)
        idx += 1
    if min_composite is not None:
        conditions.append(f"composite_score >= ${idx}")
        params.append(min_composite)
        idx += 1

    where = " AND ".join(conditions)
    query = f"SELECT COUNT(*) FROM list_accounts WHERE {where}"

    async with _db._pool.acquire() as conn:
        return await conn.fetchval(query, *params)


async def get_list_accounts(
    list_id: int,
    min_pain: int | None = None,
    min_composite: int | None = None,
    sort_by: str = "composite_score",
    order: str = "desc",
    limit: int = 100,
    offset: int = 0,
    status: str | None = None,
    account_ids: list[int] | None = None,
) -> list[dict]:
    """Get accounts for a list with optional filtering and sorting."""
    allowed_sorts = {"pain_score", "composite_score", "fit_score", "timing_score", "company_name"}
    if sort_by not in allowed_sorts:
        sort_by = "composite_score"
    if order not in ("asc", "desc"):
        order = "desc"

    conditions = ["list_id = $1"]
    params: list = [list_id]
    idx = 2

    if min_pain is not None:
        conditions.append(f"pain_score >= ${idx}")
        params.append(min_pain)
        idx += 1
    if min_composite is not None:
        conditions.append(f"composite_score >= ${idx}")
        params.append(min_composite)
        idx += 1
    if status is not None:
        conditions.append(f"status = ${idx}")
        params.append(status)
        idx += 1
    if account_ids is not None:
        conditions.append(f"id = ANY(${idx})")
        params.append(account_ids)
        idx += 1

    where = " AND ".join(conditions)
    # Use NULLS LAST so un-analyzed accounts sort to the end
    query = f"""
        SELECT id, list_id, company_url, status, document_id, research_job_id,
               pain_score, fit_score, timing_score, composite_score,
               company_name, error_message, created_at, analyzed_at,
               enrichment_status, outreach_status, pushed_to, source_id
        FROM list_accounts
        WHERE {where}
        ORDER BY {sort_by} {order} NULLS LAST
        LIMIT ${idx} OFFSET ${idx + 1}
    """
    params.extend([limit, offset])

    async with _db._pool.acquire() as conn:
        rows = await conn.fetch(query, *params)
        return [dict(row) for row in rows]


async def update_list_account(
    account_id: int,
    status: str,
    document_id: int | None = None,
    research_job_id: int | None = None,
    pain_score: int | None = None,
    fit_score: int | None = None,
    timing_score: int | None = None,
    composite_score: int | None = None,
    company_name: str | None = None,
    error_message: str | None = None,
) -> None:
    """Update a list account and atomically increment parent counters."""
    async with _db._pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                UPDATE list_accounts
                SET status = $2, document_id = $3, research_job_id = $4,
                    pain_score = $5, fit_score = $6, timing_score = $7, composite_score = $8,
                    company_name = $9, error_message = $10,
                    analyzed_at = CASE WHEN $2 IN ('completed', 'failed') THEN NOW() ELSE analyzed_at END
                WHERE id = $1
                """,
                account_id, status, document_id, research_job_id,
                pain_score, fit_score, timing_score, composite_score,
                company_name, error_message
            )
            if status == 'completed':
                await conn.execute(
                    """
                    UPDATE lists SET analyzed_accounts = analyzed_accounts + 1, updated_at = NOW()
                    WHERE id = (SELECT list_id FROM list_accounts WHERE id = $1)
                    """,
                    account_id
                )
            elif status == 'failed':
                await conn.execute(
                    """
                    UPDATE lists SET failed_accounts = failed_accounts + 1, updated_at = NOW()
                    WHERE id = (SELECT list_id FROM list_accounts WHERE id = $1)
                    """,
                    account_id
                )


async def finalize_list(list_id: int) -> dict:
    """Set final status on a list. Returns updated record."""
    async with _db._pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT total_accounts, analyzed_accounts, failed_accounts FROM lists WHERE id = $1 FOR UPDATE",
                list_id
            )
            if row["failed_accounts"] == row["total_accounts"]:
                final_status = "failed"
            elif row["failed_accounts"] > 0:
                final_status = "partial_failure"
            else:
                final_status = "completed"

            updated = await conn.fetchrow(
                """
                UPDATE lists SET status = $2, updated_at = NOW()
                WHERE id = $1
                RETURNING *
                """,
                list_id, final_status
            )
            return dict(updated)


async def update_list_status(list_id: int, status: str) -> None:
    """Update the status of a list."""
    async with _db._pool.acquire() as conn:
        await conn.execute(
            "UPDATE lists SET status = $2, updated_at = NOW() WHERE id = $1",
            list_id, status
        )


async def update_list_credits(list_id: int, credits_reserved: int) -> None:
    """Update credits reserved on a list."""
    async with _db._pool.acquire() as conn:
        await conn.execute(
            "UPDATE lists SET credits_reserved = $2, updated_at = NOW() WHERE id = $1",
            list_id, credits_reserved
        )


async def get_list_account(account_id: int, list_id: int) -> dict | None:
    """Get a single list account by ID scoped to a list."""
    async with _db._pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM list_accounts WHERE id = $1 AND list_id = $2",
            account_id, list_id
        )
        return dict(row) if row else None


async def reset_list_account(account_id: int) -> None:
    """Reset a failed list account to pending for retry."""
    async with _db._pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                UPDATE list_accounts
                SET status = 'pending', error_message = NULL, research_job_id = NULL
                WHERE id = $1
                """,
                account_id
            )
            # Decrement failed counter on parent list
            await conn.execute(
                """
                UPDATE lists SET failed_accounts = GREATEST(failed_accounts - 1, 0), updated_at = NOW()
                WHERE id = (SELECT list_id FROM list_accounts WHERE id = $1)
                """,
                account_id
            )


async def iter_pending_list_accounts(list_id: int, page_size: int = 500):
    """Async generator that yields pending list accounts in pages."""
    last_id = 0
    async with _db._pool.acquire() as conn:
        while True:
            rows = await conn.fetch(
                """SELECT id, company_url FROM list_accounts
                   WHERE list_id = $1 AND status = 'pending' AND id > $2
                   ORDER BY id LIMIT $3""",
                list_id, last_id, page_size,
            )
            if not rows:
                break
            for row in rows:
                yield dict(row)
            last_id = rows[-1]["id"]


async def get_pending_list_accounts(list_id: int) -> list[dict]:
    """Get all pending accounts for a list."""
    return [item async for item in iter_pending_list_accounts(list_id)]


async def get_list_source(list_id: int) -> dict | None:
    """Get the source metadata for a list."""
    async with _db._pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT source FROM lists WHERE id = $1",
            list_id,
        )
        if row and row["source"]:
            return json.loads(row["source"]) if isinstance(row["source"], str) else row["source"]
        return None


async def set_list_source(list_id: int, source: dict) -> None:
    """Set the source metadata for a list."""
    async with _db._pool.acquire() as conn:
        await conn.execute(
            "UPDATE lists SET source = $2::jsonb, updated_at = NOW() WHERE id = $1",
            list_id, __import__('json').dumps(source),
        )


async def update_list_account_enrichment(account_id: int, status: str, error_message: str = None) -> None:
    """Update the enrichment_status of a list account."""
    async with _db._pool.acquire() as conn:
        await conn.execute(
            "UPDATE list_accounts SET enrichment_status = $2, error_message = COALESCE($3, error_message) WHERE id = $1",
            account_id, status, error_message,
        )


async def update_list_account_outreach(account_id: int, status: str) -> None:
    """Update the outreach_status of a list account."""
    async with _db._pool.acquire() as conn:
        await conn.execute(
            "UPDATE list_accounts SET outreach_status = $2 WHERE id = $1",
            account_id, status,
        )


async def update_list_account_pushed(account_id: int, provider: str, push_data: dict) -> None:
    """Mark a list account as pushed to a provider."""
    async with _db._pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE list_accounts SET pushed_to = pushed_to || $2::jsonb
            WHERE id = $1
            """,
            account_id,
            __import__('json').dumps({provider: push_data}),
        )
