"""Integration database operations."""

from datetime import datetime

import db._pool as _db


async def upsert_integration(
    user_id: int,
    provider: str,
    access_token: str,
    refresh_token: str | None = None,
    token_expires_at: datetime | None = None,
    metadata: dict | None = None,
) -> dict:
    """Create or update an integration for a user."""
    async with _db._pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO integrations (user_id, provider, access_token, refresh_token, token_expires_at, metadata)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb)
            ON CONFLICT (user_id, provider) DO UPDATE SET
                access_token = EXCLUDED.access_token,
                refresh_token = COALESCE(EXCLUDED.refresh_token, integrations.refresh_token),
                token_expires_at = EXCLUDED.token_expires_at,
                metadata = COALESCE(EXCLUDED.metadata, integrations.metadata),
                updated_at = NOW()
            RETURNING *
            """,
            user_id, provider, access_token, refresh_token, token_expires_at,
            __import__('json').dumps(metadata or {}),
        )
        return dict(row)


async def get_integration(user_id: int, provider: str) -> dict | None:
    """Get a user's integration for a provider."""
    async with _db._pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM integrations WHERE user_id = $1 AND provider = $2",
            user_id, provider,
        )
        return dict(row) if row else None


async def get_user_integrations(user_id: int) -> list[dict]:
    """Get all integrations for a user."""
    async with _db._pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM integrations WHERE user_id = $1 ORDER BY provider",
            user_id,
        )
        return [dict(row) for row in rows]


async def delete_integration(user_id: int, provider: str) -> bool:
    """Delete a user's integration. Returns True if deleted."""
    async with _db._pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM integrations WHERE user_id = $1 AND provider = $2",
            user_id, provider,
        )
        return result == "DELETE 1"


async def update_integration_tokens(
    user_id: int,
    provider: str,
    access_token: str,
    refresh_token: str | None = None,
    token_expires_at: datetime | None = None,
) -> None:
    """Update tokens for an integration (used by refresh flow)."""
    async with _db._pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE integrations SET
                access_token = $3,
                refresh_token = COALESCE($4, refresh_token),
                token_expires_at = $5,
                updated_at = NOW()
            WHERE user_id = $1 AND provider = $2
            """,
            user_id, provider, access_token, refresh_token, token_expires_at,
        )
