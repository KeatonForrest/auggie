"""Outreach draft database operations."""

import json

from db._pool import _pool


async def save_outreach_draft(document_id: int, user_id: int, content: dict) -> int:
    """Save an outreach draft (email sequence) for a document. Returns the draft ID."""
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO outreach_drafts (document_id, user_id, content)
            VALUES ($1, $2, $3::jsonb)
            ON CONFLICT (document_id) DO UPDATE SET content = EXCLUDED.content, updated_at = NOW()
            RETURNING id
            """,
            document_id, user_id, json.dumps(content),
        )
        return row["id"]


async def get_outreach_draft(document_id: int) -> dict | None:
    """Get the outreach draft for a document."""
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM outreach_drafts WHERE document_id = $1",
            document_id,
        )
        return dict(row) if row else None
