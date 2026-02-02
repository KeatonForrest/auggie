"""pdl.py - People Data Labs integration: API key validation, company search."""

import logging

import httpx

from database import get_integration

logger = logging.getLogger(__name__)

PDL_API_BASE = "https://api.peopledatalabs.com/v5"


async def validate_api_key(api_key: str) -> bool:
    """Validate a PDL API key by making a trivial search call."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{PDL_API_BASE}/company/search",
            headers={"X-Api-Key": api_key},
            params={"sql": "SELECT * FROM company WHERE name='test'", "size": 1},
        )
        return resp.status_code == 200


async def _get_api_key(user_id: int) -> str:
    """Get a user's PDL API key from integrations table."""
    integration = await get_integration(user_id, "pdl")
    if not integration:
        raise RuntimeError("PDL not connected")
    return integration["access_token"]


async def search_companies(user_id: int, query: dict, size: int = 50) -> dict:
    """Search companies via PDL Elasticsearch query.

    Returns {"data": [...], "total": int, "scroll_token": str|None}.
    """
    api_key = await _get_api_key(user_id)
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{PDL_API_BASE}/company/search",
            headers={"X-Api-Key": api_key, "Content-Type": "application/json"},
            json={"query": query, "size": min(size, 50)},
        )
        resp.raise_for_status()
        return resp.json()
