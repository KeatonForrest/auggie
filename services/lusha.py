"""lusha.py - Lusha integration: API key validation, company search."""

import logging

import httpx

from database import get_integration

logger = logging.getLogger(__name__)

LUSHA_API_BASE = "https://api.lusha.com/v2"


async def validate_api_key(api_key: str) -> bool:
    """Validate a Lusha API key by making a lightweight company lookup."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{LUSHA_API_BASE}/company",
            headers={"api_key": api_key},
            params={"domain": "google.com"},
        )
        logger.info("Lusha validate_api_key status=%s body=%s", resp.status_code, resp.text[:500])
        # 401/403 = definitely invalid key; anything else means the key was accepted
        return resp.status_code not in (401, 403)


async def _get_api_key(user_id: int) -> str:
    """Get a user's Lusha API key from integrations table."""
    integration = await get_integration(user_id, "lusha")
    if not integration:
        raise RuntimeError("Lusha not connected")
    return integration["access_token"]


async def search_companies(user_id: int, query: str, size: int = 50) -> list:
    """Search companies via Lusha API.

    Returns a list of company dicts with id, name, website, employeeCount, etc.
    """
    api_key = await _get_api_key(user_id)
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"{LUSHA_API_BASE}/company",
            headers={"api_key": api_key},
            params={"company_name": query},
        )
        resp.raise_for_status()
        data = resp.json()
        # Normalize response to consistent format
        companies = data if isinstance(data, list) else data.get("data", data.get("companies", [data]))
        return [
            {
                "id": c.get("id") or c.get("company_id") or c.get("domain", ""),
                "name": c.get("name") or c.get("company_name", ""),
                "website": c.get("website") or c.get("domain", ""),
                "employeeCount": c.get("employee_count") or c.get("employeeCount"),
                "industry": c.get("industry", ""),
                "country": c.get("country", ""),
            }
            for c in companies
        ]
