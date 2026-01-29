"""Auggie Python SDK — AI-powered account research API client."""

from __future__ import annotations

import time
from typing import Any

import httpx

__all__ = ["AuggieClient", "AuggieError"]

DEFAULT_BASE_URL = "https://auggie.app"


class AuggieError(Exception):
    """Raised on non-2xx API responses."""

    def __init__(self, status_code: int, detail: Any = None) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"HTTP {status_code}: {detail}")


class AuggieClient:
    """Synchronous client for the Auggie API.

    Args:
        api_key: Your Auggie API key (``aug_...``).
        base_url: Override the default API base URL.
        timeout: Request timeout in seconds.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 60,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        resp = self._client.request(method, path, **kwargs)
        if resp.status_code == 204:
            return None
        if not resp.is_success:
            detail = resp.text
            try:
                detail = resp.json().get("detail", detail)
            except Exception:
                pass
            raise AuggieError(resp.status_code, detail)
        return resp.json()

    # ------------------------------------------------------------------
    # Research
    # ------------------------------------------------------------------

    def research(self, company_url: str) -> dict:
        """Submit a research job. Returns ``{"job_id": ..., "status": "processing"}``."""
        return self._request("POST", "/v1/research", json={"company_url": company_url})

    def get_research(self, job_id: int) -> dict:
        """Poll a research job by ID."""
        return self._request("GET", f"/v1/research/{job_id}")

    def research_and_poll(
        self,
        company_url: str,
        interval: float = 5,
        timeout: float = 300,
    ) -> dict:
        """Submit a research job and poll until completion or timeout.

        Args:
            company_url: The company URL to research.
            interval: Seconds between poll requests.
            timeout: Max seconds to wait before raising ``AuggieError``.

        Returns:
            The completed research job dict.
        """
        job = self.research(company_url)
        job_id = job["job_id"]
        deadline = time.monotonic() + timeout

        while True:
            result = self.get_research(job_id)
            if result.get("status") != "processing":
                return result
            if time.monotonic() > deadline:
                raise AuggieError(408, "Polling timed out")
            time.sleep(interval)

    def list_research(self) -> dict:
        """List recent research jobs."""
        return self._request("GET", "/v1/research")

    # ------------------------------------------------------------------
    # Bulk Research
    # ------------------------------------------------------------------

    def bulk_research(self, company_urls: list[str], name: str | None = None) -> dict:
        """Submit a bulk research job. Returns ``{"bulk_job_id": ..., "status": "processing", "total_items": N}``."""
        payload: dict = {"company_urls": company_urls}
        if name is not None:
            payload["name"] = name
        return self._request("POST", "/v1/research/bulk", json=payload)

    def get_bulk_job(self, bulk_job_id: int) -> dict:
        """Get bulk job progress and items."""
        return self._request("GET", f"/v1/research/bulk/{bulk_job_id}")

    def list_bulk_jobs(self) -> dict:
        """List recent bulk jobs."""
        return self._request("GET", "/v1/research/bulk")

    # ------------------------------------------------------------------
    # Sequences
    # ------------------------------------------------------------------

    def create_sequence(self, doc_id: int) -> dict:
        """Generate an outreach sequence from a completed document."""
        return self._request("POST", f"/v1/research/{doc_id}/sequence")

    # ------------------------------------------------------------------
    # Webhooks
    # ------------------------------------------------------------------

    def register_webhook(self, url: str) -> dict:
        """Register or update a webhook URL."""
        return self._request("POST", "/v1/webhooks/register", json={"url": url})

    def get_webhook(self) -> dict:
        """Get current webhook configuration."""
        return self._request("GET", "/v1/webhooks")

    def delete_webhook(self) -> None:
        """Delete webhook."""
        self._request("DELETE", "/v1/webhooks")

    # ------------------------------------------------------------------
    # Lists
    # ------------------------------------------------------------------

    def create_list(self, name: str, company_urls: list[str], analyze: bool = True) -> dict:
        """Create a persistent list. Returns ``{"list_id": ..., "name": ..., "status": ..., "total_accounts": N}``."""
        return self._request("POST", "/v1/lists", json={
            "name": name,
            "company_urls": company_urls,
            "analyze": analyze,
        })

    def get_list(self, list_id: int, **filter_params: Any) -> dict:
        """Get list details with accounts. Supports min_pain_score, min_composite_score, sort_by, order, limit, offset."""
        return self._request("GET", f"/v1/lists/{list_id}", params=filter_params or None)

    def list_lists(self) -> dict:
        """List recent lists (summaries only)."""
        return self._request("GET", "/v1/lists")

    def analyze_list(self, list_id: int) -> dict:
        """Trigger analysis on pending accounts in a list."""
        return self._request("POST", f"/v1/lists/{list_id}/analyze")

    def delete_list(self, list_id: int) -> None:
        """Delete a list and all its accounts."""
        self._request("DELETE", f"/v1/lists/{list_id}")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> AuggieClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
