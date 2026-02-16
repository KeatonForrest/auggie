"""API key authentication dependency for FastAPI."""

import logging

from fastapi import Header, HTTPException

from database import validate_api_key, get_user_by_id

logger = logging.getLogger(__name__)


async def require_api_key(authorization: str = Header(...)) -> dict:
    """FastAPI dependency that validates Bearer token API keys.

    Returns full user dict with api_key_id added.
    Raises 401 on invalid/missing key.
    """
    if not authorization.startswith("Bearer "):
        logger.warning("Invalid authorization header format", extra={"event_type": "auth_failure", "status_code": 401})
        raise HTTPException(status_code=401, detail="Invalid authorization header. Use: Bearer sk_live_...")

    raw_key = authorization[7:]  # Strip "Bearer "

    if not raw_key.startswith("sk_live_"):
        logger.warning("Invalid API key format", extra={"event_type": "auth_failure", "status_code": 401})
        raise HTTPException(status_code=401, detail="Invalid API key format")

    result = await validate_api_key(raw_key)
    if not result:
        logger.warning("Invalid or revoked API key", extra={"event_type": "auth_failure", "status_code": 401})
        raise HTTPException(status_code=401, detail="Invalid or revoked API key")

    user = await get_user_by_id(result["user_id"])
    if not user:
        logger.warning("API key valid but user not found", extra={"event_type": "auth_failure", "status_code": 401})
        raise HTTPException(status_code=401, detail="User not found")

    # Merge api_key_id into user dict so callers have everything
    user["api_key_id"] = result["api_key_id"]
    return user
