"""Watchlist database operations — recurring research scheduling."""

from datetime import datetime, timedelta, timezone
from typing import Optional

import db._pool as _db

SCHEDULE_INTERVALS = {
    "weekly": timedelta(weeks=1),
    "biweekly": timedelta(weeks=2),
    "monthly": timedelta(days=30),
}


def _next_run(schedule: str, from_dt: datetime | None = None) -> datetime:
    """Compute the next run timestamp for a given schedule."""
    base = from_dt or datetime.now(timezone.utc)
    delta = SCHEDULE_INTERVALS.get(schedule, timedelta(weeks=1))
    return base + delta


async def create_watchlist_item(
    user_id: int,
    company_url: str,
    company_name: str | None = None,
    schedule: str = "biweekly",
) -> dict:
    """Add a company to the user's watchlist. Returns the new row."""
    next_at = _next_run(schedule)
    async with _db._pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO watchlist_items (user_id, company_url, company_name, schedule, next_run_at)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (user_id, company_url) DO UPDATE
                SET status = 'active',
                    schedule = EXCLUDED.schedule,
                    next_run_at = EXCLUDED.next_run_at,
                    updated_at = NOW()
            RETURNING *
            """,
            user_id, company_url, company_name, schedule, next_at,
        )
        return dict(row)


async def get_watchlist_item(item_id: int, user_id: int) -> Optional[dict]:
    """Get a single watchlist item scoped to user."""
    async with _db._pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM watchlist_items WHERE id = $1 AND user_id = $2",
            item_id, user_id,
        )
        return dict(row) if row else None


async def list_watchlist_items(
    user_id: int, limit: int = 100, starting_after: int | None = None,
) -> tuple[list[dict], bool]:
    """List all watchlist items for a user using cursor-based pagination.

    Returns (items, has_more).
    """
    async with _db._pool.acquire() as conn:
        if starting_after is not None:
            rows = await conn.fetch(
                """
                SELECT wi.*,
                       (SELECT MAX(sc.is_significant::int) FROM watchlist_score_changes sc
                        WHERE sc.watchlist_item_id = wi.id
                          AND sc.created_at > NOW() - INTERVAL '7 days') AS has_recent_significant
                FROM watchlist_items wi
                WHERE wi.user_id = $1 AND wi.id < $2
                ORDER BY wi.id DESC
                LIMIT $3
                """,
                user_id, starting_after, limit + 1,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT wi.*,
                       (SELECT MAX(sc.is_significant::int) FROM watchlist_score_changes sc
                        WHERE sc.watchlist_item_id = wi.id
                          AND sc.created_at > NOW() - INTERVAL '7 days') AS has_recent_significant
                FROM watchlist_items wi
                WHERE wi.user_id = $1
                ORDER BY wi.id DESC
                LIMIT $2
                """,
                user_id, limit + 1,
            )
        items = [dict(row) for row in rows]
        has_more = len(items) > limit
        return items[:limit], has_more


async def update_watchlist_item(
    item_id: int,
    user_id: int,
    schedule: str | None = None,
    status: str | None = None,
) -> Optional[dict]:
    """Update schedule or status. Returns updated row or None if not found."""
    async with _db._pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE watchlist_items
            SET schedule = COALESCE($3, schedule),
                status = COALESCE($4, status),
                next_run_at = CASE
                    WHEN $4 = 'active' AND status != 'active'
                        THEN NOW() + (
                            CASE COALESCE($3, schedule)
                                WHEN 'weekly' THEN INTERVAL '1 week'
                                WHEN 'biweekly' THEN INTERVAL '2 weeks'
                                WHEN 'monthly' THEN INTERVAL '30 days'
                                ELSE INTERVAL '2 weeks'
                            END
                        )
                    ELSE next_run_at
                END,
                updated_at = NOW()
            WHERE id = $1 AND user_id = $2
            RETURNING *
            """,
            item_id, user_id, schedule, status,
        )
        return dict(row) if row else None


async def delete_watchlist_item(item_id: int, user_id: int) -> bool:
    """Remove from watchlist. Returns True if deleted."""
    async with _db._pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM watchlist_items WHERE id = $1 AND user_id = $2",
            item_id, user_id,
        )
        return result == "DELETE 1"


async def get_score_history(item_id: int, user_id: int, limit: int = 20) -> list[dict]:
    """Get score change history for a watchlist item (scoped to user)."""
    async with _db._pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT sc.* FROM watchlist_score_changes sc
            JOIN watchlist_items wi ON wi.id = sc.watchlist_item_id
            WHERE sc.watchlist_item_id = $1 AND wi.user_id = $2
            ORDER BY sc.created_at DESC
            LIMIT $3
            """,
            item_id, user_id, limit,
        )
        return [dict(row) for row in rows]


async def claim_due_items(batch_size: int = 50) -> list[dict]:
    """Atomically claim watchlist items that are due for re-research.

    Sets next_run_at far into the future to prevent double-enqueue.
    Returns claimed items.
    """
    async with _db._pool.acquire() as conn:
        rows = await conn.fetch(
            """
            UPDATE watchlist_items
            SET next_run_at = NOW() + INTERVAL '30 days'
            WHERE id = ANY(
                SELECT id FROM watchlist_items
                WHERE status = 'active' AND next_run_at <= NOW()
                ORDER BY next_run_at
                LIMIT $1
                FOR UPDATE SKIP LOCKED
            )
            RETURNING *
            """,
            batch_size,
        )
        return [dict(row) for row in rows]


async def record_score_change(
    item_id: int,
    old_doc_id: int | None,
    new_doc_id: int,
    old_scores: dict,
    new_scores: dict,
) -> dict:
    """Record a score change entry. Returns the new row."""
    deltas = [
        abs((new_scores.get(k) or 0) - (old_scores.get(k) or 0))
        for k in ("opportunity_score", "pain_score", "fit_score", "timing_score")
    ]
    is_significant = any(d >= 10 for d in deltas)

    async with _db._pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO watchlist_score_changes (
                watchlist_item_id, old_document_id, new_document_id,
                old_opportunity_score, new_opportunity_score,
                old_pain_score, new_pain_score,
                old_fit_score, new_fit_score,
                old_timing_score, new_timing_score,
                is_significant
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
            RETURNING *
            """,
            item_id, old_doc_id, new_doc_id,
            old_scores.get("opportunity_score"), new_scores.get("opportunity_score"),
            old_scores.get("pain_score"), new_scores.get("pain_score"),
            old_scores.get("fit_score"), new_scores.get("fit_score"),
            old_scores.get("timing_score"), new_scores.get("timing_score"),
            is_significant,
        )
        return dict(row)


async def complete_watchlist_run(item_id: int, new_doc_id: int, schedule: str) -> None:
    """Update a watchlist item after a successful re-research run."""
    next_at = _next_run(schedule)
    async with _db._pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE watchlist_items
            SET last_document_id = $2,
                last_run_at = NOW(),
                next_run_at = $3,
                status = 'active',
                updated_at = NOW()
            WHERE id = $1
            """,
            item_id, new_doc_id, next_at,
        )


async def mark_skipped_no_credits(item_id: int) -> None:
    """Mark item as skipped due to insufficient credits."""
    async with _db._pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE watchlist_items
            SET status = 'skipped_no_credits',
                updated_at = NOW()
            WHERE id = $1
            """,
            item_id,
        )


async def count_significant_changes(user_id: int, days: int = 7) -> int:
    """Count watchlist items with unseen significant score changes in the last N days."""
    async with _db._pool.acquire() as conn:
        return await conn.fetchval(
            """
            SELECT COUNT(DISTINCT sc.watchlist_item_id)
            FROM watchlist_score_changes sc
            JOIN watchlist_items wi ON wi.id = sc.watchlist_item_id
            WHERE wi.user_id = $1
              AND sc.is_significant = TRUE
              AND sc.seen_at IS NULL
              AND sc.created_at > NOW() - make_interval(days := $2)
            """,
            user_id, days,
        )


async def mark_changes_seen(user_id: int) -> None:
    """Mark all significant score changes as seen for this user."""
    async with _db._pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE watchlist_score_changes sc
            SET seen_at = NOW()
            FROM watchlist_items wi
            WHERE sc.watchlist_item_id = wi.id
              AND wi.user_id = $1
              AND sc.is_significant = TRUE
              AND sc.seen_at IS NULL
            """,
            user_id,
        )


async def get_watchlist_item_by_url(user_id: int, company_url: str) -> Optional[dict]:
    """Check if a company is already on the user's watchlist."""
    async with _db._pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM watchlist_items WHERE user_id = $1 AND company_url = $2",
            user_id, company_url,
        )
        return dict(row) if row else None
