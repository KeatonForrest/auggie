"""Auggie Python SDK — AI-powered account research API client."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import random
import time
import uuid
from typing import Any, AsyncIterator, Iterator

import httpx

__version__ = "0.4.0"

__all__ = [
    "AuggieClient",
    "AsyncAuggieClient",
    "AuggieError",
    "AuthenticationError",
    "InsufficientCreditsError",
    "NotFoundError",
    "ConflictError",
    "ValidationError",
    "RateLimitError",
    "InternalServerError",
    "APITimeoutError",
    "Webhook",
    "WebhookSignatureError",
    "__version__",
]

DEFAULT_BASE_URL = "https://auggie.tools"

_RETRY_STATUS_CODES = {429, 500, 502, 503, 504}
_BASE_RETRY_DELAY = 1.0
_MAX_RETRY_DELAY = 30.0


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


class AuthenticationError(AuggieError):
    """Raised on 401 responses."""


class InsufficientCreditsError(AuggieError):
    """Raised on 402 responses."""


class NotFoundError(AuggieError):
    """Raised on 404 responses."""


class ConflictError(AuggieError):
    """Raised on 409 responses."""


class ValidationError(AuggieError):
    """Raised on 422 or 400 validation_error responses."""


class RateLimitError(AuggieError):
    """Raised on 429 responses.

    Attributes:
        retry_after: Seconds to wait before retrying (from Retry-After header), or None.
    """

    def __init__(self, status_code: int, message: Any = None, code: str | None = None, retry_after: float | None = None) -> None:
        super().__init__(status_code, message, code)
        self.retry_after = retry_after


class InternalServerError(AuggieError):
    """Raised on 500/502/503 responses."""


class APITimeoutError(AuggieError):
    """Raised on 504 responses or polling timeouts."""


_STATUS_TO_ERROR: dict[int, type[AuggieError]] = {
    401: AuthenticationError,
    402: InsufficientCreditsError,
    404: NotFoundError,
    409: ConflictError,
    422: ValidationError,
    429: RateLimitError,
    500: InternalServerError,
    502: InternalServerError,
    503: InternalServerError,
    504: APITimeoutError,
}


def _parse_error(resp: httpx.Response) -> AuggieError:
    """Parse an error response into an AuggieError (or appropriate subclass)."""
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

    status = resp.status_code

    # 400 with validation_error code -> ValidationError
    if status == 400 and code == "validation_error":
        cls = ValidationError
    else:
        cls = _STATUS_TO_ERROR.get(status, AuggieError)

    if cls is RateLimitError:
        retry_after: float | None = None
        raw = resp.headers.get("retry-after")
        if raw:
            try:
                retry_after = float(raw)
            except (ValueError, TypeError):
                pass
        return RateLimitError(status, message, code, retry_after=retry_after)

    return cls(status, message, code)


def _retry_delay(resp: httpx.Response, attempt: int) -> float:
    """Compute retry delay: respect Retry-After header, else exponential backoff with jitter."""
    retry_after = resp.headers.get("retry-after")
    if retry_after:
        try:
            return min(float(retry_after), _MAX_RETRY_DELAY)
        except (ValueError, TypeError):
            pass
    delay = min(_BASE_RETRY_DELAY * (2 ** attempt), _MAX_RETRY_DELAY)
    return delay + random.uniform(0, delay * 0.25)


class AuggieClient:
    """Synchronous client for the Auggie API.

    Args:
        api_key: Your Auggie API key (``sk_live_...``).
        base_url: Override the default API base URL.
        timeout: Request timeout in seconds.
        max_retries: Max retries on transient errors (429/5xx). Set to 0 to disable.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 60,
        max_retries: int = 3,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )
        self._max_retries = max_retries

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        if method.upper() == "POST":
            kwargs.setdefault("headers", {})
            kwargs["headers"].setdefault("Idempotency-Key", str(uuid.uuid4()))
        last_resp = None
        for attempt in range(self._max_retries + 1):
            resp = self._client.request(method, path, **kwargs)
            if resp.status_code == 204:
                return None
            if resp.is_success:
                return resp.json()
            if resp.status_code not in _RETRY_STATUS_CODES or attempt >= self._max_retries:
                raise _parse_error(resp)
            last_resp = resp
            time.sleep(_retry_delay(resp, attempt))
        raise _parse_error(last_resp)

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
            timeout: Max seconds to wait before raising ``APITimeoutError``.

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
                raise APITimeoutError(408, "Polling timed out", "timeout")
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

    def bulk_research_and_poll(
        self,
        company_urls: list[str],
        name: str | None = None,
        interval: float = 5,
        timeout: float = 600,
    ) -> dict:
        """Submit a bulk research job and poll until completion or timeout.

        Args:
            company_urls: List of company URLs to research.
            name: Optional name for the bulk job.
            interval: Seconds between poll requests.
            timeout: Max seconds to wait before raising ``APITimeoutError``.

        Returns:
            The completed bulk job dict with items.
        """
        job = self.bulk_research(company_urls, name=name)
        bulk_job_id = job["bulk_job_id"]
        deadline = time.monotonic() + timeout

        while True:
            result = self.get_bulk_job(bulk_job_id)
            if result.get("status") != "processing":
                return result
            if time.monotonic() > deadline:
                raise APITimeoutError(408, "Bulk polling timed out", "timeout")
            time.sleep(interval)

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
    # Pagination iterators
    # ------------------------------------------------------------------

    def iter_research(self, limit: int = 100) -> Iterator[dict]:
        """Iterate over all research jobs, handling pagination automatically."""
        offset = 0
        while True:
            page = self.list_research(limit=limit, offset=offset)
            for item in page.get("jobs", []):
                yield item
            if not page.get("has_more", False):
                break
            offset += limit

    def iter_bulk_jobs(self, limit: int = 100) -> Iterator[dict]:
        """Iterate over all bulk jobs, handling pagination automatically."""
        offset = 0
        while True:
            page = self.list_bulk_jobs(limit=limit, offset=offset)
            for item in page.get("bulk_jobs", []):
                yield item
            if not page.get("has_more", False):
                break
            offset += limit

    def iter_lists(self, limit: int = 100) -> Iterator[dict]:
        """Iterate over all lists, handling pagination automatically."""
        offset = 0
        while True:
            page = self.list_lists(limit=limit, offset=offset)
            for item in page.get("lists", []):
                yield item
            if not page.get("has_more", False):
                break
            offset += limit

    def iter_list_accounts(self, list_id: int, limit: int = 100, **filter_params: Any) -> Iterator[dict]:
        """Iterate over all accounts in a list, handling pagination automatically."""
        offset = 0
        while True:
            page = self.get_list(list_id, limit=limit, offset=offset, **filter_params)
            for item in page.get("accounts", []):
                yield item
            if not page.get("has_more", False):
                break
            offset += limit

    def iter_watchlist(self, limit: int = 100) -> Iterator[dict]:
        """Iterate over all watchlist items, handling pagination automatically."""
        offset = 0
        while True:
            page = self.list_watchlist(limit=limit, offset=offset)
            for item in page.get("items", []):
                yield item
            if not page.get("has_more", False):
                break
            offset += limit

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
        max_retries: Max retries on transient errors (429/5xx). Set to 0 to disable.

    Usage::

        async with AsyncAuggieClient(api_key="sk_live_...") as client:
            result = await client.research_and_poll("https://example.com")
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 60,
        max_retries: int = 3,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )
        self._max_retries = max_retries

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        if method.upper() == "POST":
            kwargs.setdefault("headers", {})
            kwargs["headers"].setdefault("Idempotency-Key", str(uuid.uuid4()))
        last_resp = None
        for attempt in range(self._max_retries + 1):
            resp = await self._client.request(method, path, **kwargs)
            if resp.status_code == 204:
                return None
            if resp.is_success:
                return resp.json()
            if resp.status_code not in _RETRY_STATUS_CODES or attempt >= self._max_retries:
                raise _parse_error(resp)
            last_resp = resp
            await asyncio.sleep(_retry_delay(resp, attempt))
        raise _parse_error(last_resp)

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
                raise APITimeoutError(408, "Polling timed out", "timeout")
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

    async def bulk_research_and_poll(
        self,
        company_urls: list[str],
        name: str | None = None,
        interval: float = 5,
        timeout: float = 600,
    ) -> dict:
        """Submit a bulk research job and poll until completion or timeout.

        Args:
            company_urls: List of company URLs to research.
            name: Optional name for the bulk job.
            interval: Seconds between poll requests.
            timeout: Max seconds to wait before raising ``APITimeoutError``.

        Returns:
            The completed bulk job dict with items.
        """
        job = await self.bulk_research(company_urls, name=name)
        bulk_job_id = job["bulk_job_id"]
        deadline = time.monotonic() + timeout

        while True:
            result = await self.get_bulk_job(bulk_job_id)
            if result.get("status") != "processing":
                return result
            if time.monotonic() > deadline:
                raise APITimeoutError(408, "Bulk polling timed out", "timeout")
            await asyncio.sleep(interval)

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
    # Pagination iterators
    # ------------------------------------------------------------------

    async def iter_research(self, limit: int = 100) -> AsyncIterator[dict]:
        """Iterate over all research jobs, handling pagination automatically."""
        offset = 0
        while True:
            page = await self.list_research(limit=limit, offset=offset)
            for item in page.get("jobs", []):
                yield item
            if not page.get("has_more", False):
                break
            offset += limit

    async def iter_bulk_jobs(self, limit: int = 100) -> AsyncIterator[dict]:
        """Iterate over all bulk jobs, handling pagination automatically."""
        offset = 0
        while True:
            page = await self.list_bulk_jobs(limit=limit, offset=offset)
            for item in page.get("bulk_jobs", []):
                yield item
            if not page.get("has_more", False):
                break
            offset += limit

    async def iter_lists(self, limit: int = 100) -> AsyncIterator[dict]:
        """Iterate over all lists, handling pagination automatically."""
        offset = 0
        while True:
            page = await self.list_lists(limit=limit, offset=offset)
            for item in page.get("lists", []):
                yield item
            if not page.get("has_more", False):
                break
            offset += limit

    async def iter_list_accounts(self, list_id: int, limit: int = 100, **filter_params: Any) -> AsyncIterator[dict]:
        """Iterate over all accounts in a list, handling pagination automatically."""
        offset = 0
        while True:
            page = await self.get_list(list_id, limit=limit, offset=offset, **filter_params)
            for item in page.get("accounts", []):
                yield item
            if not page.get("has_more", False):
                break
            offset += limit

    async def iter_watchlist(self, limit: int = 100) -> AsyncIterator[dict]:
        """Iterate over all watchlist items, handling pagination automatically."""
        offset = 0
        while True:
            page = await self.list_watchlist(limit=limit, offset=offset)
            for item in page.get("items", []):
                yield item
            if not page.get("has_more", False):
                break
            offset += limit

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> AsyncAuggieClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()


# ======================================================================
# Webhook signature verification
# ======================================================================

class WebhookSignatureError(AuggieError):
    """Raised when webhook signature verification fails."""

    def __init__(self, message: str = "Webhook signature verification failed") -> None:
        super().__init__(400, message, "webhook_signature_error")


class Webhook:
    """Webhook signature verification helper.

    Usage::

        # Verify + parse in one step (Stripe pattern)
        event = Webhook.construct_event(payload, signature_header, secret)

        # Simple boolean check
        is_valid = Webhook.verify(payload, signature_header, secret)
    """

    @staticmethod
    def _normalize_payload(payload: dict | bytes | str) -> bytes:
        """Normalize payload to the canonical JSON bytes used for signing."""
        if isinstance(payload, dict):
            return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        if isinstance(payload, str):
            payload = payload.encode()
        # For bytes, try to round-trip through JSON for canonical form
        try:
            parsed = json.loads(payload)
            return json.dumps(parsed, separators=(",", ":"), sort_keys=True).encode()
        except (json.JSONDecodeError, UnicodeDecodeError):
            return payload

    @staticmethod
    def _extract_signature(header: str) -> str:
        """Extract hex signature from header, handling both 'sha256=<hex>' and bare '<hex>' formats."""
        header = header.strip()
        if header.startswith("sha256="):
            return header[7:]
        return header

    @staticmethod
    def verify(payload: dict | bytes | str, signature_header: str, secret: str) -> bool:
        """Verify a webhook signature.

        Args:
            payload: The webhook request body (dict, bytes, or str).
            signature_header: The ``X-Webhook-Signature`` header value.
            secret: Your webhook secret.

        Returns:
            True if the signature is valid.
        """
        body = Webhook._normalize_payload(payload)
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        actual = Webhook._extract_signature(signature_header)
        return hmac.compare_digest(expected, actual)

    @staticmethod
    def construct_event(payload: dict | bytes | str, signature_header: str, secret: str) -> dict:
        """Verify signature and return the parsed event payload.

        Args:
            payload: The webhook request body (dict, bytes, or str).
            signature_header: The ``X-Webhook-Signature`` header value.
            secret: Your webhook secret.

        Returns:
            The parsed event dict.

        Raises:
            WebhookSignatureError: If the signature is invalid.
        """
        if not Webhook.verify(payload, signature_header, secret):
            raise WebhookSignatureError()
        if isinstance(payload, dict):
            return payload
        if isinstance(payload, str):
            return json.loads(payload)
        return json.loads(payload.decode())
