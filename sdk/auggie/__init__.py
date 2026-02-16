"""Auggie Python SDK — AI-powered account research API client."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

__all__ = ["AuggieClient", "AsyncAuggieClient", "AuggieError"]

DEFAULT_BASE_URL = "https://auggie.tools"


class AuggieError(Exception):
    """Raised on non-2xx API responses.

    Attributes:
        status_code: HTTP status code.
        code: Machine-readable error code (e.g. ``"insufficient_credits"``).
        message: Human-readable error message.
        detail: Alias for ``message`` (backward compat).
    """

    def __init__(self, status_code: int, message: Any = None, code: str | None = None) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.detail = message  # backward compat
        parts = [f"HTTP {status_code}"]
        if code:
            parts.append(f"[{code}]")
        if message:
            parts.append(str(message))
        super().__init__(": ".join(parts))


def _parse_error(resp: httpx.Response) -> AuggieError:
    """Parse an error response into an AuggieError."""
    code = None
    message = resp.text
    try:
        body = resp.json()
        # Structured format: {"error": {"code": "...", "message": "..."}}
        if isinstance(body, dict) and "error" in body:
            err = body["error"]
            if isinstance(err, dict):
                code = err.get("code")
                message = err.get("message", message)
            else:
                message = str(err)
        # Legacy format: {"detail": "..."}
        elif isinstance(body, dict) and "detail" in body:
            message = body["detail"]
    except Exception:
        pass
    return AuggieError(resp.status_code, message, code)


class AuggieClient:
    """Synchronous client for the Auggie API.

    Args:
        api_key: Your Auggie API key (``sk_live_...``).
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
            raise _parse_error(resp)
        return resp.json()

    # ------------------------------------------------------------------
    # Account
    # ------------------------------------------------------------------

    def ping(self) -> dict:
        """Health check. Returns ``{"status": "ok", "user_id": ...}``."""
        return self._request("GET", "/v1/ping")

    def get_account(self) -> dict:
        """Get account info: credits, subscription, org, and API key usage."""
        return self._request("GET", "/v1/account")

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
                raise AuggieError(408, "Polling timed out", "timeout")
            time.sleep(interval)

    def list_research(self, limit: int = 100, offset: int = 0) -> dict:
        """List recent research jobs."""
        return self._request("GET", "/v1/research", params={"limit": limit, "offset": offset})

    def enrich(self, document_id: int, titles: list[str] | None = None) -> dict:
        """Enrich contacts for an existing research document."""
        payload: dict = {"document_id": document_id}
        if titles is not None:
            payload["titles"] = titles
        return self._request("POST", "/v1/enrich", json=payload)

    def clay_enrich(self, company_url: str) -> dict:
        """Synchronous enrichment endpoint optimized for Clay HTTP columns.

        Uses an extended timeout (130s) since the API runs the full pipeline.
        """
        return self._request(
            "POST", "/v1/clay/enrich",
            json={"company_url": company_url},
            timeout=130.0,
        )

    # ------------------------------------------------------------------
    # Sequences
    # ------------------------------------------------------------------

    def create_sequence(self, doc_id: int) -> dict:
        """Generate an outreach sequence from a completed document."""
        return self._request("POST", f"/v1/research/{doc_id}/sequence")

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

    def list_bulk_jobs(self, limit: int = 100, offset: int = 0) -> dict:
        """List recent bulk jobs."""
        return self._request("GET", "/v1/research/bulk", params={"limit": limit, "offset": offset})

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

    def list_lists(self, limit: int = 100, offset: int = 0) -> dict:
        """List recent lists (summaries only)."""
        return self._request("GET", "/v1/lists", params={"limit": limit, "offset": offset})

    def analyze_list(self, list_id: int) -> dict:
        """Trigger analysis on pending accounts in a list."""
        return self._request("POST", f"/v1/lists/{list_id}/analyze")

    def delete_list(self, list_id: int) -> None:
        """Delete a list and all its accounts."""
        self._request("DELETE", f"/v1/lists/{list_id}")

    def push_list(self, list_id: int, campaign_id: str, account_ids: list[int] | None = None) -> dict:
        """Push accounts from a list to an Instantly campaign."""
        payload: dict = {"campaign_id": campaign_id}
        if account_ids is not None:
            payload["account_ids"] = account_ids
        return self._request("POST", f"/v1/lists/{list_id}/push", json=payload)

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
    # Team
    # ------------------------------------------------------------------

    def list_team(self) -> dict:
        """List team members."""
        return self._request("GET", "/v1/team")

    def invite_member(self, email: str, role: str = "member") -> dict:
        """Invite a team member (admin only)."""
        return self._request("POST", "/v1/team/invite", json={"email": email, "role": role})

    def remove_member(self, member_id: int) -> dict:
        """Remove a team member (admin only)."""
        return self._request("DELETE", f"/v1/team/members/{member_id}")

    def change_member_role(self, member_id: int, role: str) -> dict:
        """Change a team member's role (admin only)."""
        return self._request("PATCH", f"/v1/team/members/{member_id}", json={"role": role})

    # ------------------------------------------------------------------
    # Watchlist
    # ------------------------------------------------------------------

    def add_to_watchlist(
        self, company_url: str, company_name: str | None = None, schedule: str = "biweekly",
    ) -> dict:
        """Add a company to the watchlist with a recurring schedule."""
        payload: dict = {"company_url": company_url, "schedule": schedule}
        if company_name is not None:
            payload["company_name"] = company_name
        return self._request("POST", "/v1/watchlist", json=payload)

    def list_watchlist(self, limit: int = 100, offset: int = 0) -> dict:
        """List all watched companies."""
        return self._request("GET", "/v1/watchlist", params={"limit": limit, "offset": offset})

    def update_watchlist(self, item_id: int, schedule: str | None = None, status: str | None = None) -> dict:
        """Update schedule or pause/resume a watchlist item."""
        payload: dict = {}
        if schedule is not None:
            payload["schedule"] = schedule
        if status is not None:
            payload["status"] = status
        return self._request("PATCH", f"/v1/watchlist/{item_id}", json=payload)

    def remove_from_watchlist(self, item_id: int) -> None:
        """Remove a company from the watchlist."""
        self._request("DELETE", f"/v1/watchlist/{item_id}")

    def get_watchlist_history(self, item_id: int) -> dict:
        """Get score change history for a watched company."""
        return self._request("GET", f"/v1/watchlist/{item_id}/history")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> AuggieClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


class AsyncAuggieClient:
    """Async client for the Auggie API.

    Args:
        api_key: Your Auggie API key (``sk_live_...``).
        base_url: Override the default API base URL.
        timeout: Request timeout in seconds.

    Usage::

        async with AsyncAuggieClient(api_key="sk_live_...") as client:
            result = await client.research_and_poll("https://example.com")
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 60,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        resp = await self._client.request(method, path, **kwargs)
        if resp.status_code == 204:
            return None
        if not resp.is_success:
            raise _parse_error(resp)
        return resp.json()

    # ------------------------------------------------------------------
    # Account
    # ------------------------------------------------------------------

    async def ping(self) -> dict:
        """Health check. Returns ``{"status": "ok", "user_id": ...}``."""
        return await self._request("GET", "/v1/ping")

    async def get_account(self) -> dict:
        """Get account info: credits, subscription, org, and API key usage."""
        return await self._request("GET", "/v1/account")

    # ------------------------------------------------------------------
    # Research
    # ------------------------------------------------------------------

    async def research(self, company_url: str) -> dict:
        """Submit a research job. Returns ``{"job_id": ..., "status": "processing"}``."""
        return await self._request("POST", "/v1/research", json={"company_url": company_url})

    async def get_research(self, job_id: int) -> dict:
        """Poll a research job by ID."""
        return await self._request("GET", f"/v1/research/{job_id}")

    async def research_and_poll(
        self,
        company_url: str,
        interval: float = 5,
        timeout: float = 300,
    ) -> dict:
        """Submit a research job and poll until completion or timeout."""
        job = await self.research(company_url)
        job_id = job["job_id"]
        deadline = time.monotonic() + timeout

        while True:
            result = await self.get_research(job_id)
            if result.get("status") != "processing":
                return result
            if time.monotonic() > deadline:
                raise AuggieError(408, "Polling timed out", "timeout")
            await asyncio.sleep(interval)

    async def list_research(self, limit: int = 100, offset: int = 0) -> dict:
        """List recent research jobs."""
        return await self._request("GET", "/v1/research", params={"limit": limit, "offset": offset})

    async def enrich(self, document_id: int, titles: list[str] | None = None) -> dict:
        """Enrich contacts for an existing research document."""
        payload: dict = {"document_id": document_id}
        if titles is not None:
            payload["titles"] = titles
        return await self._request("POST", "/v1/enrich", json=payload)

    async def clay_enrich(self, company_url: str) -> dict:
        """Synchronous enrichment endpoint optimized for Clay HTTP columns."""
        return await self._request(
            "POST", "/v1/clay/enrich",
            json={"company_url": company_url},
            timeout=130.0,
        )

    # ------------------------------------------------------------------
    # Sequences
    # ------------------------------------------------------------------

    async def create_sequence(self, doc_id: int) -> dict:
        """Generate an outreach sequence from a completed document."""
        return await self._request("POST", f"/v1/research/{doc_id}/sequence")

    # ------------------------------------------------------------------
    # Bulk Research
    # ------------------------------------------------------------------

    async def bulk_research(self, company_urls: list[str], name: str | None = None) -> dict:
        """Submit a bulk research job."""
        payload: dict = {"company_urls": company_urls}
        if name is not None:
            payload["name"] = name
        return await self._request("POST", "/v1/research/bulk", json=payload)

    async def get_bulk_job(self, bulk_job_id: int) -> dict:
        """Get bulk job progress and items."""
        return await self._request("GET", f"/v1/research/bulk/{bulk_job_id}")

    async def list_bulk_jobs(self, limit: int = 100, offset: int = 0) -> dict:
        """List recent bulk jobs."""
        return await self._request("GET", "/v1/research/bulk", params={"limit": limit, "offset": offset})

    # ------------------------------------------------------------------
    # Lists
    # ------------------------------------------------------------------

    async def create_list(self, name: str, company_urls: list[str], analyze: bool = True) -> dict:
        """Create a persistent list."""
        return await self._request("POST", "/v1/lists", json={
            "name": name,
            "company_urls": company_urls,
            "analyze": analyze,
        })

    async def get_list(self, list_id: int, **filter_params: Any) -> dict:
        """Get list details with accounts."""
        return await self._request("GET", f"/v1/lists/{list_id}", params=filter_params or None)

    async def list_lists(self, limit: int = 100, offset: int = 0) -> dict:
        """List recent lists (summaries only)."""
        return await self._request("GET", "/v1/lists", params={"limit": limit, "offset": offset})

    async def analyze_list(self, list_id: int) -> dict:
        """Trigger analysis on pending accounts in a list."""
        return await self._request("POST", f"/v1/lists/{list_id}/analyze")

    async def delete_list(self, list_id: int) -> None:
        """Delete a list and all its accounts."""
        await self._request("DELETE", f"/v1/lists/{list_id}")

    async def push_list(self, list_id: int, campaign_id: str, account_ids: list[int] | None = None) -> dict:
        """Push accounts from a list to an Instantly campaign."""
        payload: dict = {"campaign_id": campaign_id}
        if account_ids is not None:
            payload["account_ids"] = account_ids
        return await self._request("POST", f"/v1/lists/{list_id}/push", json=payload)

    # ------------------------------------------------------------------
    # Webhooks
    # ------------------------------------------------------------------

    async def register_webhook(self, url: str) -> dict:
        """Register or update a webhook URL."""
        return await self._request("POST", "/v1/webhooks/register", json={"url": url})

    async def get_webhook(self) -> dict:
        """Get current webhook configuration."""
        return await self._request("GET", "/v1/webhooks")

    async def delete_webhook(self) -> None:
        """Delete webhook."""
        await self._request("DELETE", "/v1/webhooks")

    # ------------------------------------------------------------------
    # Team
    # ------------------------------------------------------------------

    async def list_team(self) -> dict:
        """List team members."""
        return await self._request("GET", "/v1/team")

    async def invite_member(self, email: str, role: str = "member") -> dict:
        """Invite a team member (admin only)."""
        return await self._request("POST", "/v1/team/invite", json={"email": email, "role": role})

    async def remove_member(self, member_id: int) -> dict:
        """Remove a team member (admin only)."""
        return await self._request("DELETE", f"/v1/team/members/{member_id}")

    async def change_member_role(self, member_id: int, role: str) -> dict:
        """Change a team member's role (admin only)."""
        return await self._request("PATCH", f"/v1/team/members/{member_id}", json={"role": role})

    # ------------------------------------------------------------------
    # Watchlist
    # ------------------------------------------------------------------

    async def add_to_watchlist(
        self, company_url: str, company_name: str | None = None, schedule: str = "biweekly",
    ) -> dict:
        """Add a company to the watchlist with a recurring schedule."""
        payload: dict = {"company_url": company_url, "schedule": schedule}
        if company_name is not None:
            payload["company_name"] = company_name
        return await self._request("POST", "/v1/watchlist", json=payload)

    async def list_watchlist(self, limit: int = 100, offset: int = 0) -> dict:
        """List all watched companies."""
        return await self._request("GET", "/v1/watchlist", params={"limit": limit, "offset": offset})

    async def update_watchlist(self, item_id: int, schedule: str | None = None, status: str | None = None) -> dict:
        """Update schedule or pause/resume a watchlist item."""
        payload: dict = {}
        if schedule is not None:
            payload["schedule"] = schedule
        if status is not None:
            payload["status"] = status
        return await self._request("PATCH", f"/v1/watchlist/{item_id}", json=payload)

    async def remove_from_watchlist(self, item_id: int) -> None:
        """Remove a company from the watchlist."""
        await self._request("DELETE", f"/v1/watchlist/{item_id}")

    async def get_watchlist_history(self, item_id: int) -> dict:
        """Get score change history for a watched company."""
        return await self._request("GET", f"/v1/watchlist/{item_id}/history")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> AsyncAuggieClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()
