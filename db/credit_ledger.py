"""Credit ledger — audit trail for every credit mutation."""

import logging
from typing import Optional

import db._pool as _db

logger = logging.getLogger(__name__)


async def record_credit_event(
    org_id: int,
    amount_cents: int,
    balance_after: int,
    operation: str,
    reference_type: Optional[str] = None,
    reference_id: Optional[int] = None,
    api_key_id: Optional[int] = None,
) -> None:
    """Insert a ledger entry. Called after any credit mutation."""
    try:
        async with _db._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO credit_ledger
                    (org_id, amount_cents, balance_after, operation, reference_type, reference_id, api_key_id)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                org_id, amount_cents, balance_after, operation,
                reference_type, reference_id, api_key_id,
            )
    except Exception:
        # Ledger is non-fatal — never block the main operation
        logger.warning("Failed to record credit ledger entry", exc_info=True)


async def get_credit_history(org_id: int, limit: int = 50) -> list[dict]:
    """Retrieve recent credit ledger entries for an organization."""
    async with _db._pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, amount_cents, balance_after, operation,
                   reference_type, reference_id, api_key_id, created_at
            FROM credit_ledger
            WHERE org_id = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            org_id, limit,
        )
        return [dict(r) for r in rows]
