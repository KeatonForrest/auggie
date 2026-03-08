"""Idempotency key helpers for API routes."""

from typing import Optional

from fastapi import Request
from fastapi.responses import JSONResponse

from db.idempotency import (
    claim_idempotency_key as db_claim,
    save_idempotency_result as db_save,
    IdempotencyKeyInProgress,
)


async def check_idempotency(
    request: Request, api_key_id: int
) -> tuple[Optional[str], Optional[JSONResponse]]:
    """Extract and atomically claim the Idempotency-Key header.

    Returns (key, cached_response):
      - (None, None)         if no header present — caller proceeds normally
      - (key, JSONResponse)  if key found in DB — caller returns cached response
      - (key, None)          if key is new (claimed) — caller proceeds and should save after
    """
    key = request.headers.get("idempotency-key")
    if not key:
        return None, None

    try:
        cached = await db_claim(api_key_id, key)
    except IdempotencyKeyInProgress:
        return key, JSONResponse(
            content={"error": {"code": "conflict", "message": "A request with this idempotency key is already in progress"}},
            status_code=409,
        )
    if cached:
        status_code, body = cached
        return key, JSONResponse(content=body, status_code=status_code)

    return key, None


async def save_idempotency(api_key_id: int, key: str, status_code: int, body: dict) -> None:
    """Persist the result for a previously claimed idempotency key."""
    await db_save(api_key_id, key, status_code, body)
