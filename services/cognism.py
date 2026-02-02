"""cognism.py - Cognism integration: API key validation, filter-based company search."""

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
        logger.info("Cognism validate_api_key status=%s body=%s", resp.status_code, resp.text[:500])
        return resp.status_code not in (401, 403)


async def _get_api_key(user_id: int) -> str:
    """Get a user's Cognism API key from integrations table."""
    integration = await get_integration(user_id, "cognism")
    if not integration:
        raise RuntimeError("Cognism not connected")
    return integration["access_token"]


async def search_companies(user_id: int, filters: dict, size: int = 50) -> dict:
    """Search companies via Cognism API with filters.

    Accepts a filters dict with keys like companyName, industry, location,
    minEmployees, maxEmployees, etc. and converts to Cognism API format.

    Returns {"data": [...], "total": int}.
    """
    api_key = await _get_api_key(user_id)

    # Build Cognism filter structure
    cognism_filters = {}
    if filters.get("industry"):
        cognism_filters["industry"] = [filters["industry"]]
    if filters.get("location"):
        cognism_filters["country"] = [filters["location"]]
    if filters.get("minEmployees"):
        cognism_filters["employeeCountMin"] = int(filters["minEmployees"])
    if filters.get("maxEmployees"):
        cognism_filters["employeeCountMax"] = int(filters["maxEmployees"])

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{COGNISM_API_BASE}/account/search",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"filters": cognism_filters, "limit": min(size, 50)},
        )
        resp.raise_for_status()
        data = resp.json()
        companies = data if isinstance(data, list) else data.get("data", data.get("items", data.get("accounts", [])))
        return {
            "data": [
                {
                    "id": c.get("id") or c.get("companyId", ""),
                    "name": c.get("companyName") or c.get("name", ""),
                    "website": c.get("website") or c.get("domain", ""),
                    "employee_count": c.get("employeeCount") or c.get("employee_count"),
                    "industry": c.get("industry", ""),
                    "country": c.get("country", ""),
                }
                for c in companies
            ],
            "total": data.get("totalResults", len(companies)) if isinstance(data, dict) else len(companies),
        }
