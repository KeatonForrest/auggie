"""API key authentication dependency for FastAPI."""

from fastapi import Header, HTTPException

from database import validate_api_key


async def require_api_key(authorization: str = Header(...)) -> dict:
    """FastAPI dependency that validates Bearer token API keys.

    Returns dict with user_id and api_key_id on success.
    Raises 401 on invalid/missing key.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header. Use: Bearer sk_live_...")

    raw_key = authorization[7:]  # Strip "Bearer "

    if not raw_key.startswith("sk_live_"):
        raise HTTPException(status_code=401, detail="Invalid API key format")

    result = await validate_api_key(raw_key)
    if not result:
        raise HTTPException(status_code=401, detail="Invalid or revoked API key")

    return result
