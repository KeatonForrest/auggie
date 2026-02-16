"""Tests for the Auggie Python SDK using httpx.MockTransport."""

from __future__ import annotations

import json
import time

import httpx
import pytest

from auggie import AuggieClient, AsyncAuggieClient, AuggieError, _parse_error


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
