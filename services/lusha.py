"""lusha.py - Lusha integration: API key validation, filter-based company search."""

import logging

import httpx

from database import get_integration

logger = logging.getLogger(__name__)

LUSHA_API_BASE = "https://api.lusha.com"


async def validate_api_key(api_key: str) -> bool:
    """Validate a Lusha API key by making a lightweight company enrichment call."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{LUSHA_API_BASE}/v2/company",
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


async def search_companies(user_id: int, filters: dict, size: int = 50) -> dict:
    """Search companies via Lusha Prospecting API with filters.

    Accepts a filters dict with keys like companyName, industry, location,
    minEmployees, maxEmployees, etc. and converts to Lusha API format.

    Returns {"data": [...], "total": int}.
    """
    api_key = await _get_api_key(user_id)

    # Build Lusha prospecting filter structure
    include = {}
    if filters.get("companyName"):
        include["companyName"] = [filters["companyName"]]
    if filters.get("industry"):
        include["industry"] = [filters["industry"]]
    if filters.get("location"):
        include["companyLocation"] = [filters["location"]]
    if filters.get("minEmployees") or filters.get("maxEmployees"):
        size_filter = {}
        if filters.get("minEmployees"):
            size_filter["min"] = int(filters["minEmployees"])
        if filters.get("maxEmployees"):
            size_filter["max"] = int(filters["maxEmployees"])
        include["companySize"] = size_filter

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{LUSHA_API_BASE}/prospecting/company/search",
            headers={"api_key": api_key, "Content-Type": "application/json"},
            json={
                "filters": {"include": include},
                "pageLength": min(size, 50),
                "currentPage": 1,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        companies = data.get("companies", [])
        return {
            "data": [
                {
                    "id": c.get("companyId") or c.get("id", ""),
                    "name": c.get("companyName") or c.get("name", ""),
                    "website": c.get("website") or c.get("domain", ""),
                    "employee_count": c.get("employeeCount") or c.get("employee_count"),
                    "industry": c.get("industry", ""),
                    "country": c.get("country", ""),
                }
                for c in companies
            ],
            "total": data.get("totalResults", len(companies)),
        }
