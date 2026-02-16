"""Idempotency key helpers for API routes."""

from typing import Optional

from fastapi import Request
from fastapi.responses import JSONResponse

from db.idempotency import (
    check_idempotency as db_check,
    save_idempotency as db_save,
)


async def check_idempotency(
    request: Request, api_key_id: int
) -> tuple[Optional[str], Optional[JSONResponse]]:
    """Extract and check the Idempotency-Key header.

    Returns (key, cached_response):
      - (None, None)         if no header present — caller proceeds normally
      - (key, JSONResponse)  if key found in DB — caller returns cached response
      - (key, None)          if key is new — caller proceeds and should save after
    """
    key = request.headers.get("idempotency-key")
    if not key:
        return None, None

    cached = await db_check(api_key_id, key)
    if cached:
        status_code, body = cached
        return key, JSONResponse(content=body, status_code=status_code)

    return key, None


async def save_idempotency(api_key_id: int, key: str, status_code: int, body: dict) -> None:
    """Persist an idempotency result. Delegates to DB layer."""
    await db_save(api_key_id, key, status_code, body)
