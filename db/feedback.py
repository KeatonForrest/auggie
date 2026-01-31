"""Research feedback database operations."""

from typing import Optional

import db._pool as _db


async def save_feedback(document_id: int, user_id: int, is_positive: bool, comment: Optional[str] = None):
    """Upsert feedback for a document (one per user per document)."""
    async with _db._pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO research_feedback (document_id, user_id, is_positive, comment)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (document_id, user_id)
            DO UPDATE SET is_positive = $3, comment = $4, created_at = NOW()
            """,
            document_id, user_id, is_positive, comment,
        )


async def get_feedback(document_id: int, user_id: int) -> Optional[dict]:
    """Get existing feedback for a document by a user."""
    async with _db._pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT is_positive, comment FROM research_feedback WHERE document_id = $1 AND user_id = $2",
            document_id, user_id,
        )
        if row:
            return {"is_positive": row["is_positive"], "comment": row["comment"]}
        return None


async def get_all_feedback(limit: int = 100) -> list[dict]:
    """Get all feedback joined with document model_used and scores for A/B analysis."""
    async with _db._pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT f.id, f.document_id, f.user_id, f.is_positive, f.comment, f.created_at,
                   d.model_used, d.opportunity_score, d.pain_score, d.fit_score, d.timing_score,
                   d.company_name
            FROM research_feedback f
            JOIN research_documents d ON d.id = f.document_id
            ORDER BY f.created_at DESC
            LIMIT $1
            """,
            limit,
        )
        return [dict(r) for r in rows]
