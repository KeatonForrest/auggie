"""Route-level tests for GET /v1/lists/{list_id} — next_cursor and invalid cursor handling."""

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from api.auth import require_api_key
from api.pagination import encode_composite_cursor


FAKE_USER = {
    "id": 1,
    "email": "test@test.com",
    "name": "Test User",
    "org_id": 1,
    "api_key_id": 99,
}

FAKE_LIST = {
    "id": 10,
    "name": "Enterprise Targets",
    "status": "completed",
    "total_accounts": 2,
    "analyzed_accounts": 2,
    "failed_accounts": 0,
}


def _make_account(id, company_name="Example Inc.", composite_score=80):
    return {
        "id": id,
        "company_url": f"https://example{id}.com",
        "company_name": company_name,
        "status": "completed",
        "document_id": id * 10,
        "pain_score": 75,
        "fit_score": 70,
        "timing_score": 65,
        "composite_score": composite_score,
        "analyzed_at": datetime(2026, 1, 15, 10, 30),
    }


@pytest_asyncio.fixture
async def api_client():
    """Async HTTP client with API key auth mocked."""
    from main import app

    async def _fake_api_key():
        return FAKE_USER

    app.dependency_overrides[require_api_key] = _fake_api_key
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.pop(require_api_key, None)


class TestListEndpointNextCursor:
    @pytest.mark.asyncio
    async def test_next_cursor_present_when_has_more(self, api_client):
        """Response includes next_cursor when has_more=true."""
        accounts = [_make_account(1), _make_account(2)]
        with patch("api.routes.get_list", new_callable=AsyncMock, return_value=FAKE_LIST), \
             patch("api.routes.get_list_accounts", new_callable=AsyncMock, return_value=(accounts, True)):

            resp = await api_client.get("/v1/lists/10?limit=2")

        assert resp.status_code == 200
        data = resp.json()
        cursor = data["accounts"]["next_cursor"]
        assert cursor is not None
        assert isinstance(cursor, str)
        assert len(cursor) > 0

    @pytest.mark.asyncio
    async def test_next_cursor_none_when_no_more(self, api_client):
        """Response has next_cursor=null when has_more=false."""
        accounts = [_make_account(1)]
        with patch("api.routes.get_list", new_callable=AsyncMock, return_value=FAKE_LIST), \
             patch("api.routes.get_list_accounts", new_callable=AsyncMock, return_value=(accounts, False)):

            resp = await api_client.get("/v1/lists/10")

        assert resp.status_code == 200
        data = resp.json()
        assert data["accounts"]["next_cursor"] is None
        assert data["accounts"]["has_more"] is False

    @pytest.mark.asyncio
    async def test_next_cursor_round_trips(self, api_client):
        """Cursor returned on page 1 can be sent as starting_after on page 2."""
        page1_accounts = [_make_account(1, composite_score=90), _make_account(2, composite_score=80)]
        page2_accounts = [_make_account(3, composite_score=70)]

        call_count = 0

        async def mock_get_list_accounts(list_id, **kwargs):
            nonlocal call_count
            call_count += 1
            if kwargs.get("starting_after") is None:
                return (page1_accounts, True)
            return (page2_accounts, False)

        with patch("api.routes.get_list", new_callable=AsyncMock, return_value=FAKE_LIST), \
             patch("api.routes.get_list_accounts", side_effect=mock_get_list_accounts):

            resp1 = await api_client.get("/v1/lists/10?limit=2")
            assert resp1.status_code == 200
            cursor = resp1.json()["accounts"]["next_cursor"]

            resp2 = await api_client.get(f"/v1/lists/10?limit=2&starting_after={cursor}")
            assert resp2.status_code == 200
            assert resp2.json()["accounts"]["next_cursor"] is None
            assert call_count == 2


class TestListEndpointInvalidCursor:
    @pytest.mark.asyncio
    async def test_malformed_base64_returns_422(self, api_client):
        """Malformed base64 starting_after returns 422."""
        with patch("api.routes.get_list", new_callable=AsyncMock, return_value=FAKE_LIST):
            resp = await api_client.get("/v1/lists/10?starting_after=not!valid!base64@@@")

        assert resp.status_code == 422
        data = resp.json()
        assert data["error"]["code"] == "validation_error"
        assert "cursor" in data["error"]["message"].lower()

    @pytest.mark.asyncio
    async def test_non_cursor_base64_returns_422(self, api_client):
        """Valid base64 that doesn't decode to a proper cursor returns 422."""
        import base64
        bad_cursor = base64.urlsafe_b64encode(b"nocolon").decode()
        with patch("api.routes.get_list", new_callable=AsyncMock, return_value=FAKE_LIST):
            resp = await api_client.get(f"/v1/lists/10?starting_after={bad_cursor}")

        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_valid_cursor_passes_validation(self, api_client):
        """A properly encoded cursor does not trigger 422."""
        cursor = encode_composite_cursor(80, 5)
        accounts = [_make_account(6)]
        with patch("api.routes.get_list", new_callable=AsyncMock, return_value=FAKE_LIST), \
             patch("api.routes.get_list_accounts", new_callable=AsyncMock, return_value=(accounts, False)):
            resp = await api_client.get(f"/v1/lists/10?starting_after={cursor}")

        assert resp.status_code == 200
