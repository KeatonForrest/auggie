"""Idempotency key storage for POST endpoint deduplication."""

import json
from typing import Optional

import db._pool as _db


async def check_idempotency(api_key_id: int, key: str) -> Optional[tuple[int, dict]]:
    """Look up an idempotency key. Returns (status_code, body) or None."""
    async with _db._pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT status_code, response_body FROM idempotency_keys "
            "WHERE api_key_id = $1 AND idempotency_key = $2",
            api_key_id, key,
        )
        if row:
            return row["status_code"], json.loads(row["response_body"])
        return None


async def save_idempotency(api_key_id: int, key: str, status_code: int, body: dict) -> None:
    """Store an idempotency key result. INSERT ON CONFLICT DO NOTHING."""
    async with _db._pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO idempotency_keys (api_key_id, idempotency_key, status_code, response_body) "
            "VALUES ($1, $2, $3, $4::jsonb) ON CONFLICT (api_key_id, idempotency_key) DO NOTHING",
            api_key_id, key, status_code, json.dumps(body),
        )


async def cleanup_expired_keys() -> int:
    """Delete idempotency keys older than 24 hours. Returns count deleted."""
    async with _db._pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM idempotency_keys WHERE created_at < now() - INTERVAL '24 hours'"
        )
        # asyncpg returns e.g. "DELETE 5"
        return int(result.split()[-1])
