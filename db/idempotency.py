"""Idempotency key storage for POST endpoint deduplication.

Uses atomic INSERT ON CONFLICT to prevent race conditions where two
concurrent requests with the same key both pass the check and execute.
"""

import json
from typing import Optional

import db._pool as _db


async def claim_idempotency_key(api_key_id: int, key: str) -> Optional[tuple[int, dict]]:
    """Atomically claim an idempotency key or return cached result.

    Returns:
        None — key claimed, caller should proceed and call save_idempotency_result() after.
        (status_code, body) — key already has a result, caller should return cached response.

    Raises:
        IdempotencyKeyInProgress — another request claimed this key but hasn't finished yet.
    """
    async with _db._pool.acquire() as conn:
        # Attempt atomic claim: insert a pending row.
        # ON CONFLICT means another request already owns this key.
        row = await conn.fetchrow(
            """
            INSERT INTO idempotency_keys (api_key_id, idempotency_key, status_code, response_body)
            VALUES ($1, $2, 0, '{}')
            ON CONFLICT (api_key_id, idempotency_key) DO NOTHING
            RETURNING id
            """,
            api_key_id, key,
        )
        if row is not None:
            # We claimed the key — caller proceeds with the request
            return None

        # Key already exists — check if it has a real result
        existing = await conn.fetchrow(
            "SELECT status_code, response_body FROM idempotency_keys "
            "WHERE api_key_id = $1 AND idempotency_key = $2",
            api_key_id, key,
        )
        if existing and existing["status_code"] != 0:
            return existing["status_code"], json.loads(existing["response_body"])

        # Key exists but status_code=0 means another request is still processing
        raise IdempotencyKeyInProgress()


async def save_idempotency_result(api_key_id: int, key: str, status_code: int, body: dict) -> None:
    """Store the result for a previously claimed idempotency key."""
    async with _db._pool.acquire() as conn:
        await conn.execute(
            "UPDATE idempotency_keys SET status_code = $3, response_body = $4::jsonb "
            "WHERE api_key_id = $1 AND idempotency_key = $2",
            api_key_id, key, status_code, json.dumps(body),
        )


class IdempotencyKeyInProgress(Exception):
    """Raised when another request is currently processing the same idempotency key."""
    pass


async def cleanup_expired_keys() -> int:
    """Delete idempotency keys older than 24 hours. Returns count deleted."""
    async with _db._pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM idempotency_keys WHERE created_at < now() - INTERVAL '24 hours'"
        )
        # asyncpg returns e.g. "DELETE 5"
        return int(result.split()[-1])
