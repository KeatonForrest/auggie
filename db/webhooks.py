"""Webhook database operations."""

from typing import Optional

import db._pool as _db


async def upsert_webhook(user_id: int, url: str, secret: str) -> dict:
    """Create or update user's webhook (org-scoped). Returns the webhook record."""
    async with _db._pool.acquire() as conn:
        org_id = await conn.fetchval("SELECT org_id FROM users WHERE id = $1", user_id)
        row = await conn.fetchrow(
            """
            INSERT INTO webhooks (user_id, url, secret, org_id)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (user_id) DO UPDATE
            SET url = EXCLUDED.url, secret = EXCLUDED.secret, active = TRUE, org_id = EXCLUDED.org_id
            RETURNING *
            """,
            user_id, url, secret, org_id
        )
        return dict(row)


async def get_user_webhook(user_id: int) -> Optional[dict]:
    """Get a user's active webhook config."""
    async with _db._pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM webhooks WHERE user_id = $1 AND active = TRUE",
            user_id
        )
        return dict(row) if row else None


async def delete_user_webhook(user_id: int) -> bool:
    """Deactivate user's webhook. Returns True if found."""
    async with _db._pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE webhooks SET active = FALSE WHERE user_id = $1 AND active = TRUE",
            user_id
        )
        return result == "UPDATE 1"


async def create_webhook_delivery(webhook_id: int, job_id: int) -> dict:
    """Create a delivery record. Returns the record."""
    async with _db._pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO webhook_deliveries (webhook_id, job_id)
            VALUES ($1, $2)
            RETURNING *
            """,
            webhook_id, job_id
        )
        return dict(row)


async def update_delivery_status(
    delivery_id: int,
    status: str,
    http_status: int = None,
    error_message: str = None,
    attempts: int = None,
) -> None:
    """Update a webhook delivery result.

    If attempts is provided, sets the column directly; otherwise increments by 1.
    """
    async with _db._pool.acquire() as conn:
        if attempts is not None:
            await conn.execute(
                """
                UPDATE webhook_deliveries
                SET status = $2, http_status = $3, error_message = $4, attempts = $5
                WHERE id = $1
                """,
                delivery_id, status, http_status, error_message, attempts
            )
        else:
            await conn.execute(
                """
                UPDATE webhook_deliveries
                SET status = $2, http_status = $3, error_message = $4, attempts = attempts + 1
                WHERE id = $1
                """,
                delivery_id, status, http_status, error_message
            )
