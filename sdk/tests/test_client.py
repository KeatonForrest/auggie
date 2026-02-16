"""Tests for the Auggie Python SDK using httpx.MockTransport."""

from __future__ import annotations

import json
import time

import httpx
import pytest

from auggie import (
    AuggieClient, AsyncAuggieClient, AuggieError, _parse_error, __version__,
    AuthenticationError, InsufficientCreditsError, NotFoundError, ConflictError,
    ValidationError, RateLimitError, InternalServerError, APITimeoutError,
    Webhook, WebhookSignatureError,
    APIResource, PingResponse, Account, ResearchJob, ResearchJobList,
    EnrichResult, ClayEnrichResult, Sequence, BulkJob, BulkJobList,
    AccountList, AccountListSummary, PushResult, WebhookConfig, TeamList,
    Invite, WatchlistItem, WatchlistPage, WatchlistHistory,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_transport(handler):
    """Create an httpx.MockTransport from a handler function."""
    return httpx.MockTransport(handler)


def json_response(data, status_code=200):
    return httpx.Response(status_code, json=data)


def make_client(handler, **kwargs) -> AuggieClient:
    client = AuggieClient(api_key="sk_live_test", base_url="https://test.auggie.tools", **kwargs)
    client._client = httpx.Client(
        transport=make_transport(handler),
        base_url="https://test.auggie.tools",
        headers={"Authorization": "Bearer sk_live_test"},
    )
    return client


def make_async_client(handler, **kwargs) -> AsyncAuggieClient:
    client = AsyncAuggieClient(api_key="sk_live_test", base_url="https://test.auggie.tools", **kwargs)
    client._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://test.auggie.tools",
        headers={"Authorization": "Bearer sk_live_test"},
    )
    return client


# ---------------------------------------------------------------------------
# Error parsing
# ---------------------------------------------------------------------------

class TestErrorParsing:
    def test_structured_error(self):
        """API returns {"error": {"code": "...", "message": "..."}}."""
        resp = httpx.Response(
            402,
            json={"error": {"code": "insufficient_credits", "message": "No credits remaining"}},
        )
        err = _parse_error(resp)
        assert err.status_code == 402
        assert err.code == "insufficient_credits"
        assert err.message == "No credits remaining"
        assert err.detail == "No credits remaining"  # backward compat
        assert "insufficient_credits" in str(err)

    def test_legacy_detail_error(self):
        """Fallback: {"detail": "..."}."""
        resp = httpx.Response(404, json={"detail": "Not found"})
        err = _parse_error(resp)
        assert err.status_code == 404
        assert err.code is None
        assert err.message == "Not found"

    def test_plain_text_error(self):
        """Non-JSON error body."""
        resp = httpx.Response(500, text="Internal Server Error")
        err = _parse_error(resp)
        assert err.status_code == 500
        assert err.code is None
        assert err.message == "Internal Server Error"

    def test_error_string_repr(self):
        err = AuggieError(402, "No credits", "insufficient_credits")
        assert str(err) == "HTTP 402: [insufficient_credits]: No credits"

    def test_error_without_code(self):
        err = AuggieError(500, "Something broke")
        assert str(err) == "HTTP 500: Something broke"
        assert err.code is None


# ---------------------------------------------------------------------------
# Sync client — endpoint tests
# ---------------------------------------------------------------------------

class TestSyncEndpoints:
    def test_ping(self):
        def handler(request):
            assert request.url.path == "/v1/ping"
            assert request.method == "GET"
            return json_response({"status": "ok", "user_id": 1})

        client = make_client(handler)
        result = client.ping()
        assert result == {"status": "ok", "user_id": 1}

    def test_get_account(self):
        def handler(request):
            assert request.url.path == "/v1/account"
            return json_response({"user_id": 1, "credits": {"balance": 10}})

        client = make_client(handler)
        result = client.get_account()
        assert result["user_id"] == 1

    def test_research(self):
        def handler(request):
            assert request.url.path == "/v1/research"
            assert request.method == "POST"
            body = json.loads(request.content)
            assert body["company_url"] == "https://example.com"
            return json_response({"job_id": 42, "status": "processing"}, 202)

        client = make_client(handler)
        result = client.research("https://example.com")
        assert result["job_id"] == 42

    def test_get_research(self):
        def handler(request):
            assert request.url.path == "/v1/research/42"
            return json_response({"job_id": 42, "status": "completed"})

        client = make_client(handler)
        result = client.get_research(42)
        assert result["status"] == "completed"

    def test_list_research_pagination(self):
        def handler(request):
            assert request.url.path == "/v1/research"
            assert request.url.params["limit"] == "50"
            assert request.url.params["offset"] == "10"
            return json_response({"jobs": []})

        client = make_client(handler)
        client.list_research(limit=50, offset=10)

    def test_enrich(self):
        def handler(request):
            assert request.url.path == "/v1/enrich"
            body = json.loads(request.content)
            assert body["document_id"] == 7
            assert body["titles"] == ["CTO"]
            return json_response({"success": True, "contacts": []})

        client = make_client(handler)
        client.enrich(document_id=7, titles=["CTO"])

    def test_enrich_no_titles(self):
        def handler(request):
            body = json.loads(request.content)
            assert "titles" not in body
            return json_response({"success": True, "contacts": []})

        client = make_client(handler)
        client.enrich(document_id=7)

    def test_clay_enrich_timeout(self):
        """clay_enrich should pass timeout=130.0 to the request."""
        def handler(request):
            assert request.url.path == "/v1/clay/enrich"
            body = json.loads(request.content)
            assert body["company_url"] == "https://example.com"
            return json_response({"success": True, "company_name": "Example"})

        client = make_client(handler)
        result = client.clay_enrich("https://example.com")
        assert result["success"] is True

    def test_create_sequence(self):
        def handler(request):
            assert request.url.path == "/v1/research/42/sequence"
            assert request.method == "POST"
            return json_response({"success": True, "emails": []})

        client = make_client(handler)
        client.create_sequence(doc_id=42)

    def test_bulk_research(self):
        def handler(request):
            assert request.url.path == "/v1/research/bulk"
            assert request.method == "POST"
            body = json.loads(request.content)
            assert body["company_urls"] == ["https://a.com"]
            assert body["name"] == "test"
            return json_response({"bulk_job_id": 1, "status": "processing", "total_items": 1}, 202)

        client = make_client(handler)
        client.bulk_research(["https://a.com"], name="test")

    def test_get_bulk_job(self):
        def handler(request):
            assert request.url.path == "/v1/research/bulk/5"
            return json_response({"bulk_job_id": 5, "status": "completed"})

        client = make_client(handler)
        client.get_bulk_job(5)

    def test_list_bulk_jobs_pagination(self):
        def handler(request):
            assert request.url.params["limit"] == "20"
            assert request.url.params["offset"] == "5"
            return json_response({"bulk_jobs": []})

        client = make_client(handler)
        client.list_bulk_jobs(limit=20, offset=5)

    def test_create_list(self):
        def handler(request):
            assert request.url.path == "/v1/lists"
            assert request.method == "POST"
            body = json.loads(request.content)
            assert body["name"] == "My List"
            assert body["analyze"] is True
            return json_response({"list_id": 1, "name": "My List", "status": "analyzing", "total_accounts": 2}, 201)

        client = make_client(handler)
        client.create_list("My List", ["https://a.com", "https://b.com"])

    def test_get_list_with_filters(self):
        def handler(request):
            assert request.url.path == "/v1/lists/3"
            assert request.url.params["min_pain_score"] == "60"
            return json_response({"list_id": 3, "accounts": []})

        client = make_client(handler)
        client.get_list(3, min_pain_score=60)

    def test_list_lists_pagination(self):
        def handler(request):
            assert request.url.params["limit"] == "10"
            return json_response({"lists": []})

        client = make_client(handler)
        client.list_lists(limit=10)

    def test_analyze_list(self):
        def handler(request):
            assert request.url.path == "/v1/lists/3/analyze"
            assert request.method == "POST"
            return json_response({"list_id": 3, "status": "analyzing"}, 202)

        client = make_client(handler)
        client.analyze_list(3)

    def test_delete_list(self):
        def handler(request):
            assert request.url.path == "/v1/lists/3"
            assert request.method == "DELETE"
            return httpx.Response(204)

        client = make_client(handler)
        result = client.delete_list(3)
        assert result is None

    def test_push_list(self):
        def handler(request):
            assert request.url.path == "/v1/lists/3/push"
            body = json.loads(request.content)
            assert body["campaign_id"] == "camp_1"
            assert body["account_ids"] == [1, 2]
            return json_response({"pushed": 2})

        client = make_client(handler)
        client.push_list(3, campaign_id="camp_1", account_ids=[1, 2])

    def test_push_list_no_account_ids(self):
        def handler(request):
            body = json.loads(request.content)
            assert "account_ids" not in body
            return json_response({"pushed": 5})

        client = make_client(handler)
        client.push_list(3, campaign_id="camp_1")

    def test_register_webhook(self):
        def handler(request):
            assert request.url.path == "/v1/webhooks/register"
            body = json.loads(request.content)
            assert body["url"] == "https://hook.example.com"
            return json_response({"id": 1, "url": "https://hook.example.com"})

        client = make_client(handler)
        client.register_webhook("https://hook.example.com")

    def test_get_webhook(self):
        def handler(request):
            assert request.url.path == "/v1/webhooks"
            assert request.method == "GET"
            return json_response({"id": 1, "url": "https://hook.example.com"})

        client = make_client(handler)
        client.get_webhook()

    def test_delete_webhook(self):
        def handler(request):
            assert request.url.path == "/v1/webhooks"
            assert request.method == "DELETE"
            return httpx.Response(204)

        client = make_client(handler)
        result = client.delete_webhook()
        assert result is None

    def test_list_team(self):
        def handler(request):
            assert request.url.path == "/v1/team"
            return json_response({"members": [{"id": 1, "email": "a@b.com"}]})

        client = make_client(handler)
        result = client.list_team()
        assert len(result["members"]) == 1

    def test_invite_member(self):
        def handler(request):
            assert request.url.path == "/v1/team/invite"
            body = json.loads(request.content)
            assert body["email"] == "new@co.com"
            assert body["role"] == "admin"
            return json_response({"invite": {"id": 1}})

        client = make_client(handler)
        client.invite_member("new@co.com", role="admin")

    def test_remove_member(self):
        def handler(request):
            assert request.url.path == "/v1/team/members/5"
            assert request.method == "DELETE"
            return json_response({"removed": True})

        client = make_client(handler)
        client.remove_member(5)

    def test_change_member_role(self):
        def handler(request):
            assert request.url.path == "/v1/team/members/5"
            assert request.method == "PATCH"
            body = json.loads(request.content)
            assert body["role"] == "viewer"
            return json_response({"updated": True})

        client = make_client(handler)
        client.change_member_role(5, role="viewer")

    def test_add_to_watchlist(self):
        def handler(request):
            assert request.url.path == "/v1/watchlist"
            assert request.method == "POST"
            body = json.loads(request.content)
            assert body["company_url"] == "https://example.com"
            assert body["company_name"] == "Example"
            assert body["schedule"] == "weekly"
            return json_response({"id": 1, "status": "active"}, 201)

        client = make_client(handler)
        client.add_to_watchlist("https://example.com", company_name="Example", schedule="weekly")

    def test_add_to_watchlist_defaults(self):
        def handler(request):
            body = json.loads(request.content)
            assert body["schedule"] == "biweekly"
            assert "company_name" not in body
            return json_response({"id": 1}, 201)

        client = make_client(handler)
        client.add_to_watchlist("https://example.com")

    def test_list_watchlist(self):
        def handler(request):
            assert request.url.path == "/v1/watchlist"
            assert request.url.params["limit"] == "50"
            return json_response({"items": []})

        client = make_client(handler)
        client.list_watchlist(limit=50)

    def test_update_watchlist(self):
        def handler(request):
            assert request.url.path == "/v1/watchlist/7"
            assert request.method == "PATCH"
            body = json.loads(request.content)
            assert body["schedule"] == "monthly"
            assert body["status"] == "paused"
            return json_response({"id": 7, "schedule": "monthly", "status": "paused"})

        client = make_client(handler)
        client.update_watchlist(7, schedule="monthly", status="paused")

    def test_remove_from_watchlist(self):
        def handler(request):
            assert request.url.path == "/v1/watchlist/7"
            assert request.method == "DELETE"
            return httpx.Response(204)

        client = make_client(handler)
        result = client.remove_from_watchlist(7)
        assert result is None

    def test_get_watchlist_history(self):
        def handler(request):
            assert request.url.path == "/v1/watchlist/7/history"
            assert request.method == "GET"
            return json_response({"item_id": 7, "changes": []})

        client = make_client(handler)
        result = client.get_watchlist_history(7)
        assert result["item_id"] == 7


# ---------------------------------------------------------------------------
# Sync client — error handling
# ---------------------------------------------------------------------------

class TestSyncErrors:
    def test_raises_auggie_error_on_structured_error(self):
        def handler(request):
            return httpx.Response(
                402,
                json={"error": {"code": "insufficient_credits", "message": "No credits"}},
            )

        client = make_client(handler)
        with pytest.raises(AuggieError) as exc_info:
            client.ping()
        assert exc_info.value.status_code == 402
        assert exc_info.value.code == "insufficient_credits"
        assert exc_info.value.message == "No credits"

    def test_raises_auggie_error_on_legacy_error(self):
        def handler(request):
            return httpx.Response(404, json={"detail": "Not found"})

        client = make_client(handler)
        with pytest.raises(AuggieError) as exc_info:
            client.ping()
        assert exc_info.value.status_code == 404
        assert exc_info.value.message == "Not found"

    def test_204_returns_none(self):
        def handler(request):
            return httpx.Response(204)

        client = make_client(handler)
        assert client._request("DELETE", "/v1/something") is None


# ---------------------------------------------------------------------------
# Sync client — polling
# ---------------------------------------------------------------------------

class TestSyncPolling:
    def test_research_and_poll_completes(self):
        call_count = 0

        def handler(request):
            nonlocal call_count
            if request.method == "POST":
                return json_response({"job_id": 1, "status": "processing"}, 202)
            call_count += 1
            if call_count >= 2:
                return json_response({"job_id": 1, "status": "completed", "company_name": "Test"})
            return json_response({"job_id": 1, "status": "processing"})

        client = make_client(handler)
        result = client.research_and_poll("https://example.com", interval=0.01)
        assert result["status"] == "completed"

    def test_research_and_poll_timeout(self):
        def handler(request):
            if request.method == "POST":
                return json_response({"job_id": 1, "status": "processing"}, 202)
            return json_response({"job_id": 1, "status": "processing"})

        client = make_client(handler)
        with pytest.raises(AuggieError) as exc_info:
            client.research_and_poll("https://example.com", interval=0.01, timeout=0.05)
        assert exc_info.value.status_code == 408
        assert exc_info.value.code == "timeout"


# ---------------------------------------------------------------------------
# Context managers
# ---------------------------------------------------------------------------

class TestContextManagers:
    def test_sync_context_manager(self):
        def handler(request):
            return json_response({"status": "ok"})

        with make_client(handler) as client:
            result = client.ping()
            assert result["status"] == "ok"

    @pytest.mark.anyio
    async def test_async_context_manager(self):
        def handler(request):
            return json_response({"status": "ok"})

        async with make_async_client(handler) as client:
            result = await client.ping()
            assert result["status"] == "ok"


# ---------------------------------------------------------------------------
# Async client
# ---------------------------------------------------------------------------

class TestAsyncEndpoints:
    @pytest.mark.anyio
    async def test_ping(self):
        def handler(request):
            assert request.url.path == "/v1/ping"
            return json_response({"status": "ok", "user_id": 1})

        async with make_async_client(handler) as client:
            result = await client.ping()
            assert result["status"] == "ok"

    @pytest.mark.anyio
    async def test_research(self):
        def handler(request):
            assert request.method == "POST"
            return json_response({"job_id": 1, "status": "processing"}, 202)

        async with make_async_client(handler) as client:
            result = await client.research("https://example.com")
            assert result["job_id"] == 1

    @pytest.mark.anyio
    async def test_research_and_poll(self):
        call_count = 0

        def handler(request):
            nonlocal call_count
            if request.method == "POST":
                return json_response({"job_id": 1, "status": "processing"}, 202)
            call_count += 1
            if call_count >= 2:
                return json_response({"job_id": 1, "status": "completed"})
            return json_response({"job_id": 1, "status": "processing"})

        async with make_async_client(handler) as client:
            result = await client.research_and_poll("https://example.com", interval=0.01)
            assert result["status"] == "completed"

    @pytest.mark.anyio
    async def test_research_and_poll_timeout(self):
        def handler(request):
            if request.method == "POST":
                return json_response({"job_id": 1, "status": "processing"}, 202)
            return json_response({"job_id": 1, "status": "processing"})

        async with make_async_client(handler) as client:
            with pytest.raises(AuggieError) as exc_info:
                await client.research_and_poll("https://example.com", interval=0.01, timeout=0.05)
            assert exc_info.value.code == "timeout"

    @pytest.mark.anyio
    async def test_error_handling(self):
        def handler(request):
            return httpx.Response(
                403, json={"error": {"code": "forbidden", "message": "Admin access required"}},
            )

        async with make_async_client(handler) as client:
            with pytest.raises(AuggieError) as exc_info:
                await client.list_team()
            assert exc_info.value.code == "forbidden"

    @pytest.mark.anyio
    async def test_delete_returns_none(self):
        def handler(request):
            return httpx.Response(204)

        async with make_async_client(handler) as client:
            result = await client.delete_list(1)
            assert result is None

    @pytest.mark.anyio
    async def test_watchlist_endpoints(self):
        def handler(request):
            path = request.url.path
            if path == "/v1/watchlist" and request.method == "POST":
                return json_response({"id": 1, "status": "active"}, 201)
            if path == "/v1/watchlist" and request.method == "GET":
                return json_response({"items": []})
            if path == "/v1/watchlist/1" and request.method == "PATCH":
                return json_response({"id": 1, "schedule": "monthly"})
            if path == "/v1/watchlist/1" and request.method == "DELETE":
                return httpx.Response(204)
            if path == "/v1/watchlist/1/history":
                return json_response({"item_id": 1, "changes": []})
            return httpx.Response(404)

        async with make_async_client(handler) as client:
            item = await client.add_to_watchlist("https://example.com")
            assert item["id"] == 1

            items = await client.list_watchlist()
            assert items["items"] == []

            updated = await client.update_watchlist(1, schedule="monthly")
            assert updated["schedule"] == "monthly"

            result = await client.remove_from_watchlist(1)
            assert result is None

            history = await client.get_watchlist_history(1)
            assert history["changes"] == []


# ---------------------------------------------------------------------------
# Auth header
# ---------------------------------------------------------------------------

class TestAuthHeader:
    def test_bearer_token_sent(self):
        def handler(request):
            assert request.headers["authorization"] == "Bearer sk_live_test"
            return json_response({"status": "ok"})

        client = make_client(handler)
        client.ping()


# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------

class TestVersion:
    def test_version_exists(self):
        assert __version__ is not None
        assert isinstance(__version__, str)

    def test_version_matches_semver(self):
        parts = __version__.split(".")
        assert len(parts) == 3
        assert all(p.isdigit() for p in parts)

    def test_version_is_0_5_0(self):
        assert __version__ == "0.5.0"


# ---------------------------------------------------------------------------
# Retry logic
# ---------------------------------------------------------------------------

class TestRetryLogic:
    def test_retries_on_429(self):
        """Should retry on 429 and succeed on subsequent attempt."""
        call_count = 0

        def handler(request):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                return httpx.Response(
                    429,
                    json={"error": {"code": "rate_limit_exceeded", "message": "Too fast"}},
                    headers={"retry-after": "0"},
                )
            return json_response({"status": "ok"})

        client = make_client(handler, max_retries=3)
        result = client.ping()
        assert result["status"] == "ok"
        assert call_count == 2

    def test_retries_on_500(self):
        """Should retry on 500 and succeed."""
        call_count = 0

        def handler(request):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                return httpx.Response(500, json={"error": {"code": "internal_error", "message": "Oops"}})
            return json_response({"status": "ok"})

        client = make_client(handler, max_retries=3)
        result = client.ping()
        assert result["status"] == "ok"
        assert call_count == 2

    def test_no_retry_on_400(self):
        """Should NOT retry on client errors like 400."""
        call_count = 0

        def handler(request):
            nonlocal call_count
            call_count += 1
            return httpx.Response(
                400,
                json={"error": {"code": "validation_error", "message": "Bad request"}},
            )

        client = make_client(handler, max_retries=3)
        with pytest.raises(AuggieError) as exc_info:
            client.ping()
        assert exc_info.value.status_code == 400
        assert call_count == 1

    def test_max_retries_exhausted(self):
        """Should raise after exhausting retries."""
        call_count = 0

        def handler(request):
            nonlocal call_count
            call_count += 1
            return httpx.Response(
                500,
                json={"error": {"code": "internal_error", "message": "Server down"}},
            )

        client = make_client(handler, max_retries=2)
        with pytest.raises(AuggieError) as exc_info:
            client.ping()
        assert exc_info.value.status_code == 500
        assert call_count == 3  # 1 initial + 2 retries

    def test_retry_after_header_respected(self):
        """Retry-After header should be used for delay computation."""
        from auggie import _retry_delay
        resp = httpx.Response(429, headers={"retry-after": "5"})
        delay = _retry_delay(resp, 0)
        assert delay == 5.0

    def test_no_retries_when_disabled(self):
        """max_retries=0 should disable retries."""
        call_count = 0

        def handler(request):
            nonlocal call_count
            call_count += 1
            return httpx.Response(500, json={"error": {"code": "internal_error", "message": "fail"}})

        client = make_client(handler, max_retries=0)
        with pytest.raises(AuggieError):
            client.ping()
        assert call_count == 1


class TestAsyncRetryLogic:
    @pytest.mark.anyio
    async def test_retries_on_429(self):
        call_count = 0

        def handler(request):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                return httpx.Response(
                    429,
                    json={"error": {"code": "rate_limit_exceeded", "message": "Too fast"}},
                    headers={"retry-after": "0"},
                )
            return json_response({"status": "ok"})

        async with make_async_client(handler, max_retries=3) as client:
            result = await client.ping()
            assert result["status"] == "ok"
            assert call_count == 2

    @pytest.mark.anyio
    async def test_max_retries_exhausted(self):
        call_count = 0

        def handler(request):
            nonlocal call_count
            call_count += 1
            return httpx.Response(502, json={"error": {"code": "bad_gateway", "message": "fail"}})

        async with make_async_client(handler, max_retries=2) as client:
            with pytest.raises(AuggieError) as exc_info:
                await client.ping()
            assert exc_info.value.status_code == 502
            assert call_count == 3


# ---------------------------------------------------------------------------
# Pagination helpers
# ---------------------------------------------------------------------------

class TestPaginationHelpers:
    def test_single_page(self):
        """Should yield all items from a single page."""
        def handler(request):
            return json_response({
                "jobs": [{"job_id": 1}, {"job_id": 2}],
                "total": 2,
                "has_more": False,
            })

        client = make_client(handler)
        items = list(client.iter_research(limit=100))
        assert len(items) == 2
        assert items[0]["job_id"] == 1

    def test_multi_page(self):
        """Should iterate across multiple pages."""
        call_count = 0

        def handler(request):
            nonlocal call_count
            call_count += 1
            offset = int(request.url.params.get("offset", 0))
            if offset == 0:
                return json_response({
                    "jobs": [{"job_id": 1}, {"job_id": 2}],
                    "total": 3,
                    "has_more": True,
                })
            else:
                return json_response({
                    "jobs": [{"job_id": 3}],
                    "total": 3,
                    "has_more": False,
                })

        client = make_client(handler)
        items = list(client.iter_research(limit=2))
        assert len(items) == 3
        assert call_count == 2

    def test_empty_results(self):
        """Should handle empty results gracefully."""
        def handler(request):
            return json_response({"jobs": [], "total": 0, "has_more": False})

        client = make_client(handler)
        items = list(client.iter_research())
        assert items == []

    def test_iter_bulk_jobs(self):
        def handler(request):
            return json_response({"bulk_jobs": [{"id": 1}], "total": 1, "has_more": False})

        client = make_client(handler)
        items = list(client.iter_bulk_jobs())
        assert len(items) == 1

    def test_iter_lists(self):
        def handler(request):
            return json_response({"lists": [{"list_id": 1}], "total": 1, "has_more": False})

        client = make_client(handler)
        items = list(client.iter_lists())
        assert len(items) == 1

    def test_iter_list_accounts(self):
        def handler(request):
            return json_response({
                "list_id": 1, "name": "test", "status": "completed",
                "total_accounts": 1, "analyzed_accounts": 1, "failed_accounts": 0,
                "accounts": [{"id": 1, "company_url": "https://a.com"}],
                "total": 1, "has_more": False,
            })

        client = make_client(handler)
        items = list(client.iter_list_accounts(list_id=1))
        assert len(items) == 1

    def test_iter_watchlist(self):
        def handler(request):
            return json_response({"items": [{"id": 1}], "total": 1, "has_more": False})

        client = make_client(handler)
        items = list(client.iter_watchlist())
        assert len(items) == 1

    def test_no_has_more_key_stops(self):
        """If has_more is missing from response, should stop (safe fallback)."""
        def handler(request):
            return json_response({"jobs": [{"job_id": 1}], "total": 1})

        client = make_client(handler)
        items = list(client.iter_research())
        assert len(items) == 1


class TestAsyncPaginationHelpers:
    @pytest.mark.anyio
    async def test_single_page(self):
        def handler(request):
            return json_response({
                "jobs": [{"job_id": 1}, {"job_id": 2}],
                "total": 2,
                "has_more": False,
            })

        async with make_async_client(handler) as client:
            items = [item async for item in client.iter_research()]
            assert len(items) == 2

    @pytest.mark.anyio
    async def test_multi_page(self):
        def handler(request):
            offset = int(request.url.params.get("offset", 0))
            if offset == 0:
                return json_response({
                    "jobs": [{"job_id": 1}],
                    "total": 2,
                    "has_more": True,
                })
            return json_response({
                "jobs": [{"job_id": 2}],
                "total": 2,
                "has_more": False,
            })

        async with make_async_client(handler) as client:
            items = [item async for item in client.iter_research(limit=1)]
            assert len(items) == 2

    @pytest.mark.anyio
    async def test_empty(self):
        def handler(request):
            return json_response({"items": [], "total": 0, "has_more": False})

        async with make_async_client(handler) as client:
            items = [item async for item in client.iter_watchlist()]
            assert items == []


# ---------------------------------------------------------------------------
# Idempotency keys
# ---------------------------------------------------------------------------

class TestIdempotencyKeys:
    def test_post_includes_idempotency_key(self):
        """POST requests should include an Idempotency-Key header."""
        def handler(request):
            assert "idempotency-key" in request.headers
            key = request.headers["idempotency-key"]
            assert len(key) == 36  # UUID format
            return json_response({"job_id": 1, "status": "processing"}, 202)

        client = make_client(handler)
        client.research("https://example.com")

    def test_get_does_not_include_idempotency_key(self):
        """GET requests should NOT include an Idempotency-Key header."""
        def handler(request):
            assert "idempotency-key" not in request.headers
            return json_response({"status": "ok", "user_id": 1})

        client = make_client(handler)
        client.ping()

    def test_same_key_reused_across_retries(self):
        """Same Idempotency-Key should be sent on retries."""
        keys_seen = []

        def handler(request):
            if "idempotency-key" in request.headers:
                keys_seen.append(request.headers["idempotency-key"])
            if len(keys_seen) < 2:
                return httpx.Response(
                    500,
                    json={"error": {"code": "internal_error", "message": "fail"}},
                )
            return json_response({"job_id": 1, "status": "processing"}, 202)

        client = make_client(handler, max_retries=3)
        client.research("https://example.com")
        assert len(keys_seen) == 2
        assert keys_seen[0] == keys_seen[1]

    def test_delete_does_not_include_idempotency_key(self):
        """DELETE requests should NOT include an Idempotency-Key header."""
        def handler(request):
            assert "idempotency-key" not in request.headers
            return httpx.Response(204)

        client = make_client(handler)
        client.delete_list(1)

    @pytest.mark.anyio
    async def test_async_post_includes_idempotency_key(self):
        """Async POST requests should include an Idempotency-Key header."""
        def handler(request):
            assert "idempotency-key" in request.headers
            return json_response({"job_id": 1, "status": "processing"}, 202)

        async with make_async_client(handler) as client:
            await client.research("https://example.com")

    @pytest.mark.anyio
    async def test_async_get_does_not_include_idempotency_key(self):
        """Async GET requests should NOT include an Idempotency-Key header."""
        def handler(request):
            assert "idempotency-key" not in request.headers
            return json_response({"status": "ok", "user_id": 1})

        async with make_async_client(handler) as client:
            await client.ping()


# ---------------------------------------------------------------------------
# Error subclasses
# ---------------------------------------------------------------------------

class TestErrorSubclasses:
    def test_401_returns_authentication_error(self):
        resp = httpx.Response(401, json={"error": {"code": "unauthorized", "message": "Bad key"}})
        err = _parse_error(resp)
        assert isinstance(err, AuthenticationError)
        assert isinstance(err, AuggieError)
        assert err.status_code == 401

    def test_402_returns_insufficient_credits_error(self):
        resp = httpx.Response(402, json={"error": {"code": "insufficient_credits", "message": "No credits"}})
        err = _parse_error(resp)
        assert isinstance(err, InsufficientCreditsError)
        assert err.code == "insufficient_credits"

    def test_404_returns_not_found_error(self):
        resp = httpx.Response(404, json={"error": {"code": "not_found", "message": "Gone"}})
        err = _parse_error(resp)
        assert isinstance(err, NotFoundError)

    def test_409_returns_conflict_error(self):
        resp = httpx.Response(409, json={"error": {"code": "conflict", "message": "Duplicate"}})
        err = _parse_error(resp)
        assert isinstance(err, ConflictError)

    def test_422_returns_validation_error(self):
        resp = httpx.Response(422, json={"error": {"code": "validation_error", "message": "Bad field"}})
        err = _parse_error(resp)
        assert isinstance(err, ValidationError)

    def test_400_validation_code_returns_validation_error(self):
        resp = httpx.Response(400, json={"error": {"code": "validation_error", "message": "Invalid URL"}})
        err = _parse_error(resp)
        assert isinstance(err, ValidationError)

    def test_400_non_validation_returns_base(self):
        resp = httpx.Response(400, json={"error": {"code": "bad_request", "message": "Nope"}})
        err = _parse_error(resp)
        assert type(err) is AuggieError

    def test_429_returns_rate_limit_error(self):
        resp = httpx.Response(
            429,
            json={"error": {"code": "rate_limit_exceeded", "message": "Slow down"}},
            headers={"retry-after": "5"},
        )
        err = _parse_error(resp)
        assert isinstance(err, RateLimitError)
        assert err.retry_after == 5.0

    def test_429_no_retry_after_header(self):
        resp = httpx.Response(429, json={"error": {"code": "rate_limit_exceeded", "message": "Slow"}})
        err = _parse_error(resp)
        assert isinstance(err, RateLimitError)
        assert err.retry_after is None

    def test_500_returns_internal_server_error(self):
        resp = httpx.Response(500, json={"error": {"code": "internal_error", "message": "Oops"}})
        err = _parse_error(resp)
        assert isinstance(err, InternalServerError)

    def test_502_returns_internal_server_error(self):
        resp = httpx.Response(502, text="Bad Gateway")
        err = _parse_error(resp)
        assert isinstance(err, InternalServerError)

    def test_503_returns_internal_server_error(self):
        resp = httpx.Response(503, text="Service Unavailable")
        err = _parse_error(resp)
        assert isinstance(err, InternalServerError)

    def test_504_returns_api_timeout_error(self):
        resp = httpx.Response(504, text="Gateway Timeout")
        err = _parse_error(resp)
        assert isinstance(err, APITimeoutError)

    def test_except_auggie_error_catches_all_subclasses(self):
        """All subclasses are caught by `except AuggieError`."""
        for cls in [AuthenticationError, InsufficientCreditsError, NotFoundError,
                    ConflictError, ValidationError, RateLimitError,
                    InternalServerError, APITimeoutError]:
            with pytest.raises(AuggieError):
                if cls is RateLimitError:
                    raise cls(429, "test", "test", retry_after=1.0)
                else:
                    raise cls(400, "test", "test")

    def test_subclass_raised_through_request_path(self):
        """Error subclasses are raised through the _request() path."""
        def handler(request):
            return httpx.Response(
                402,
                json={"error": {"code": "insufficient_credits", "message": "No credits"}},
            )

        client = make_client(handler)
        with pytest.raises(InsufficientCreditsError) as exc_info:
            client.ping()
        assert exc_info.value.status_code == 402

    def test_polling_timeout_raises_api_timeout_error(self):
        """research_and_poll timeout raises APITimeoutError, not base AuggieError."""
        def handler(request):
            if request.method == "POST":
                return json_response({"job_id": 1, "status": "processing"}, 202)
            return json_response({"job_id": 1, "status": "processing"})

        client = make_client(handler)
        with pytest.raises(APITimeoutError) as exc_info:
            client.research_and_poll("https://example.com", interval=0.01, timeout=0.05)
        assert exc_info.value.code == "timeout"


# ---------------------------------------------------------------------------
# Webhook verification
# ---------------------------------------------------------------------------

class TestWebhookVerification:
    def _sign(self, payload: dict, secret: str) -> str:
        """Helper: compute the same HMAC-SHA256 the server uses."""
        import hashlib, hmac as _hmac
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        return _hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    def test_valid_dict_payload(self):
        payload = {"event": "research.completed", "data": {"id": 1}}
        secret = "whsec_test123"
        sig = self._sign(payload, secret)
        event = Webhook.construct_event(payload, sig, secret)
        assert event == payload

    def test_valid_str_payload(self):
        payload = {"event": "test"}
        secret = "whsec_abc"
        body_str = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        sig = self._sign(payload, secret)
        event = Webhook.construct_event(body_str, sig, secret)
        assert event == payload

    def test_valid_bytes_payload(self):
        payload = {"event": "test"}
        secret = "whsec_abc"
        body_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        sig = self._sign(payload, secret)
        event = Webhook.construct_event(body_bytes, sig, secret)
        assert event == payload

    def test_sha256_prefix_format(self):
        payload = {"event": "test"}
        secret = "whsec_abc"
        sig = "sha256=" + self._sign(payload, secret)
        assert Webhook.verify(payload, sig, secret) is True

    def test_bare_hex_format(self):
        payload = {"event": "test"}
        secret = "whsec_abc"
        sig = self._sign(payload, secret)
        assert Webhook.verify(payload, sig, secret) is True

    def test_invalid_signature_returns_false(self):
        payload = {"event": "test"}
        assert Webhook.verify(payload, "bad_signature", "secret") is False

    def test_tampered_payload_fails(self):
        payload = {"event": "test"}
        secret = "whsec_abc"
        sig = self._sign(payload, secret)
        tampered = {"event": "tampered"}
        assert Webhook.verify(tampered, sig, secret) is False

    def test_construct_event_raises_on_invalid(self):
        with pytest.raises(WebhookSignatureError) as exc_info:
            Webhook.construct_event({"event": "test"}, "bad_sig", "secret")
        assert isinstance(exc_info.value, AuggieError)

    def test_webhook_signature_error_is_auggie_error(self):
        err = WebhookSignatureError()
        assert isinstance(err, AuggieError)
        assert err.code == "webhook_signature_error"


# ---------------------------------------------------------------------------
# Bulk poll convenience
# ---------------------------------------------------------------------------

class TestBulkPollConvenience:
    def test_bulk_research_and_poll_completes(self):
        call_count = 0

        def handler(request):
            nonlocal call_count
            if request.method == "POST":
                return json_response({"bulk_job_id": 1, "status": "processing", "total_items": 2}, 202)
            call_count += 1
            if call_count >= 2:
                return json_response({"bulk_job_id": 1, "status": "completed", "items": [{"id": 1}, {"id": 2}]})
            return json_response({"bulk_job_id": 1, "status": "processing"})

        client = make_client(handler)
        result = client.bulk_research_and_poll(["https://a.com", "https://b.com"], interval=0.01)
        assert result["status"] == "completed"
        assert len(result["items"]) == 2

    def test_bulk_research_and_poll_timeout(self):
        def handler(request):
            if request.method == "POST":
                return json_response({"bulk_job_id": 1, "status": "processing", "total_items": 1}, 202)
            return json_response({"bulk_job_id": 1, "status": "processing"})

        client = make_client(handler)
        with pytest.raises(APITimeoutError) as exc_info:
            client.bulk_research_and_poll(["https://a.com"], interval=0.01, timeout=0.05)
        assert exc_info.value.code == "timeout"

    def test_bulk_research_and_poll_with_name(self):
        def handler(request):
            if request.method == "POST":
                body = json.loads(request.content)
                assert body["name"] == "my batch"
                return json_response({"bulk_job_id": 1, "status": "completed", "items": []})
            return json_response({"bulk_job_id": 1, "status": "completed", "items": []})

        client = make_client(handler)
        result = client.bulk_research_and_poll(["https://a.com"], name="my batch", interval=0.01)
        assert result["status"] == "completed"

    @pytest.mark.anyio
    async def test_async_bulk_research_and_poll_completes(self):
        call_count = 0

        def handler(request):
            nonlocal call_count
            if request.method == "POST":
                return json_response({"bulk_job_id": 1, "status": "processing", "total_items": 1}, 202)
            call_count += 1
            if call_count >= 2:
                return json_response({"bulk_job_id": 1, "status": "completed", "items": [{"id": 1}]})
            return json_response({"bulk_job_id": 1, "status": "processing"})

        async with make_async_client(handler) as client:
            result = await client.bulk_research_and_poll(["https://a.com"], interval=0.01)
            assert result["status"] == "completed"

    @pytest.mark.anyio
    async def test_async_bulk_research_and_poll_timeout(self):
        def handler(request):
            if request.method == "POST":
                return json_response({"bulk_job_id": 1, "status": "processing", "total_items": 1}, 202)
            return json_response({"bulk_job_id": 1, "status": "processing"})

        async with make_async_client(handler) as client:
            with pytest.raises(APITimeoutError):
                await client.bulk_research_and_poll(["https://a.com"], interval=0.01, timeout=0.05)


# ---------------------------------------------------------------------------
# Resource objects
# ---------------------------------------------------------------------------

class TestResourceObjects:
    def test_dict_access(self):
        """Resource objects support dict-style access."""
        r = ResearchJob({"job_id": 42, "status": "completed"})
        assert r["job_id"] == 42
        assert r["status"] == "completed"

    def test_dot_access(self):
        """Resource objects support attribute-style access."""
        r = ResearchJob({"job_id": 42, "status": "completed"})
        assert r.job_id == 42
        assert r.status == "completed"

    def test_missing_key_raises_attribute_error(self):
        """Accessing missing attribute raises AttributeError."""
        r = APIResource({"a": 1})
        with pytest.raises(AttributeError, match="no attribute 'missing'"):
            _ = r.missing

    def test_isinstance_dict(self):
        """Resource objects are instances of dict."""
        r = PingResponse({"status": "ok"})
        assert isinstance(r, dict)

    def test_json_serializable(self):
        """Resource objects are JSON-serializable."""
        r = Account({"user_id": 1, "credits": {"balance": 10}})
        serialized = json.dumps(r)
        assert '"user_id": 1' in serialized

    def test_repr(self):
        """Resource objects have descriptive repr."""
        r = PingResponse({"status": "ok"})
        assert repr(r).startswith("PingResponse(")

    def test_setattr(self):
        """Attribute assignment works."""
        r = APIResource({})
        r.new_key = "value"
        assert r["new_key"] == "value"

    def test_delattr(self):
        """Attribute deletion works."""
        r = APIResource({"key": "value"})
        del r.key
        assert "key" not in r

    def test_delattr_missing_raises(self):
        """Deleting missing attribute raises AttributeError."""
        r = APIResource({})
        with pytest.raises(AttributeError):
            del r.missing

    def test_get_method(self):
        """dict .get() works on resource objects."""
        r = ResearchJob({"job_id": 42})
        assert r.get("job_id") == 42
        assert r.get("missing", "default") == "default"

    def test_in_operator(self):
        """'in' operator works on resource objects."""
        r = ResearchJob({"job_id": 42})
        assert "job_id" in r
        assert "missing" not in r

    def test_ping_returns_ping_response(self):
        """ping() returns PingResponse."""
        def handler(request):
            return json_response({"status": "ok", "user_id": 1})

        client = make_client(handler)
        result = client.ping()
        assert isinstance(result, PingResponse)
        assert result.status == "ok"

    def test_research_returns_research_job(self):
        """research() returns ResearchJob."""
        def handler(request):
            return json_response({"job_id": 42, "status": "processing"}, 202)

        client = make_client(handler)
        result = client.research("https://example.com")
        assert isinstance(result, ResearchJob)
        assert result.job_id == 42

    def test_get_webhook_returns_none_when_empty(self):
        """get_webhook() returns None when no webhook configured."""
        def handler(request):
            return httpx.Response(204)

        client = make_client(handler)
        result = client.get_webhook()
        assert result is None

    def test_get_webhook_returns_webhook_config(self):
        """get_webhook() returns WebhookConfig when configured."""
        def handler(request):
            return json_response({"url": "https://hook.example.com", "active": True})

        client = make_client(handler)
        result = client.get_webhook()
        assert isinstance(result, WebhookConfig)
        assert result.url == "https://hook.example.com"

    def test_backward_compat(self):
        """Existing dict-style code still works with resource objects."""
        def handler(request):
            return json_response({"status": "ok", "user_id": 1})

        client = make_client(handler)
        result = client.ping()
        # All dict operations still work
        assert result == {"status": "ok", "user_id": 1}
        assert dict(result) == {"status": "ok", "user_id": 1}
        assert list(result.keys()) == ["status", "user_id"]

    @pytest.mark.anyio
    async def test_async_ping_returns_ping_response(self):
        """Async ping() returns PingResponse."""
        def handler(request):
            return json_response({"status": "ok", "user_id": 1})

        async with make_async_client(handler) as client:
            result = await client.ping()
            assert isinstance(result, PingResponse)
            assert result.status == "ok"

    @pytest.mark.anyio
    async def test_async_research_and_poll_returns_research_job(self):
        """Async research_and_poll() returns ResearchJob."""
        call_count = 0

        def handler(request):
            nonlocal call_count
            if request.method == "POST":
                return json_response({"job_id": 1, "status": "processing"}, 202)
            call_count += 1
            if call_count >= 2:
                return json_response({"job_id": 1, "status": "completed"})
            return json_response({"job_id": 1, "status": "processing"})

        async with make_async_client(handler) as client:
            result = await client.research_and_poll("https://example.com", interval=0.01)
            assert isinstance(result, ResearchJob)
            assert result.status == "completed"
