"""API key database operations."""

import db._pool as _db


async def create_api_key_record(user_id: int, key_hash: str, prefix: str, name: str = "Default") -> int:
    """Store a new API key hash. Returns the key ID."""
    async with _db._pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO api_keys (user_id, key_hash, prefix, name)
            VALUES ($1, $2, $3, $4)
            RETURNING id
            """,
            user_id, key_hash, prefix, name
        )
        return row["id"]


async def validate_api_key(raw_key: str) -> dict | None:
    """Validate a raw API key against stored hashes.

    Returns {"user_id": ..., "api_key_id": ...} on success, None on failure.
    """
    from api.keys import verify_api_key

    prefix = raw_key[:16]
    async with _db._pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, user_id, key_hash FROM api_keys WHERE prefix = $1 AND NOT revoked",
            prefix
        )
        for row in rows:
            if verify_api_key(raw_key, row["key_hash"]):
                # Update last_used_at
                await conn.execute(
                    "UPDATE api_keys SET last_used_at = NOW() WHERE id = $1",
                    row["id"]
                )
                return {"user_id": row["user_id"], "api_key_id": row["id"]}
    return None


async def list_api_keys(user_id: int) -> list[dict]:
    """List all active API keys for a user (no hashes returned)."""
    async with _db._pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, prefix, name, created_at, last_used_at
            FROM api_keys
            WHERE user_id = $1 AND NOT revoked
            ORDER BY created_at DESC
            """,
            user_id
        )
        return [dict(row) for row in rows]


async def revoke_api_key(key_id: int, user_id: int) -> bool:
    """Revoke an API key (scoped to user). Returns True if revoked."""
    async with _db._pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE api_keys SET revoked = TRUE WHERE id = $1 AND user_id = $2 AND NOT revoked",
            key_id, user_id
        )
        return result == "UPDATE 1"


async def record_api_usage(api_key_id: int, endpoint: str, credits_used: int = 1):
    """Log an API call for usage tracking."""
    async with _db._pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO api_usage (api_key_id, endpoint, credits_used) VALUES ($1, $2, $3)",
            api_key_id, endpoint, credits_used
        )


async def get_api_key_usage_stats(user_id: int) -> dict[int, dict]:
    """Get per-key usage stats (request count, credits used) for a user's active keys."""
    async with _db._pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT ak.id AS key_id,
                   COALESCE(COUNT(au.id), 0) AS request_count,
                   COALESCE(SUM(au.credits_used), 0) AS credits_used
            FROM api_keys ak
            LEFT JOIN api_usage au ON au.api_key_id = ak.id
            WHERE ak.user_id = $1 AND NOT ak.revoked
            GROUP BY ak.id
            """,
            user_id
        )
        return {row["key_id"]: {"requests": row["request_count"], "credits": row["credits_used"]} for row in rows}
