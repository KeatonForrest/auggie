"""ocean.py - Ocean.io integration: API key validation, audience import."""

import logging

import httpx

from database import get_integration

logger = logging.getLogger(__name__)

OCEAN_API_BASE = "https://api.ocean.io/v1"


async def validate_api_key(api_key: str) -> bool:
    """Validate an Ocean.io API key by making a test call."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{OCEAN_API_BASE}/me",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        return resp.status_code == 200


async def _get_api_key(user_id: int) -> str:
    """Get a user's Ocean.io API key from integrations table."""
    integration = await get_integration(user_id, "ocean")
    if not integration:
        raise RuntimeError("Ocean.io not connected")
    return integration["access_token"]


async def list_audiences(user_id: int) -> list[dict]:
    """List lookalike audiences from Ocean.io."""
    api_key = await _get_api_key(user_id)
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{OCEAN_API_BASE}/audiences",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("audiences", data.get("data", []))


async def fetch_audience_companies(user_id: int, audience_id: str, page: int = 1) -> dict:
    """Fetch companies from an Ocean.io audience.

    Returns {"companies": [...], "pagination": {...}} or similar.
    """
    api_key = await _get_api_key(user_id)
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{OCEAN_API_BASE}/audiences/{audience_id}/companies",
            headers={"Authorization": f"Bearer {api_key}"},
            params={"page": page, "per_page": 100},
        )
        resp.raise_for_status()
        return resp.json()
