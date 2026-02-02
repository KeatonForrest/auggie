"""cognism.py - Cognism integration: API key validation, company search."""

import logging

import httpx

from database import get_integration

logger = logging.getLogger(__name__)

COGNISM_API_BASE = "https://app.cognism.com/api/search"


async def validate_api_key(api_key: str) -> bool:
    """Validate a Cognism API key by making a lightweight account search call."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{COGNISM_API_BASE}/account/search",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"filters": {"companyName": ["google"]}, "limit": 1},
        )
        # 200 = valid key, 401/403 = invalid key
        return resp.status_code == 200


async def _get_api_key(user_id: int) -> str:
    """Get a user's Cognism API key from integrations table."""
    integration = await get_integration(user_id, "cognism")
    if not integration:
        raise RuntimeError("Cognism not connected")
    return integration["access_token"]


async def search_companies(user_id: int, query: str, size: int = 50) -> list:
    """Search companies via Cognism API.

    Returns a list of company dicts with id, name, website, employeeCount, etc.
    """
    api_key = await _get_api_key(user_id)
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{COGNISM_API_BASE}/account/search",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"filters": {"companyName": [query]}, "limit": min(size, 50)},
        )
        resp.raise_for_status()
        data = resp.json()
        # Normalize response to consistent format
        companies = data if isinstance(data, list) else data.get("data", data.get("items", data.get("accounts", [])))
        return [
            {
                "id": c.get("id") or c.get("companyId", ""),
                "name": c.get("companyName") or c.get("name", ""),
                "website": c.get("website") or c.get("domain", ""),
                "employeeCount": c.get("employeeCount") or c.get("employee_count"),
                "industry": c.get("industry", ""),
                "country": c.get("country", ""),
            }
            for c in companies
        ]
