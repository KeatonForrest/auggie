"""
test_gong_engage.py - Tests for Gong Engage integration service and routes.
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch, MagicMock

import httpx


# =============================================================================
# Gong Engage Service Tests
# =============================================================================

class TestGongEngageAuthorizeUrl:
    def test_builds_correct_url(self):
        from services.gong_engage import get_authorize_url, GONG_AUTH_URL, SCOPES

        with patch("services.gong_engage.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                gong_engage_client_id="gong-client-id",
                app_url="https://app.example.com",
            )
            url = get_authorize_url("test-state-789")

        assert url.startswith(GONG_AUTH_URL)
        assert "client_id=gong-client-id" in url
        assert "state=test-state-789" in url
        assert "redirect_uri=https://app.example.com/integrations/gong_engage/callback" in url or \
               "redirect_uri=https%3A//app.example.com/integrations/gong_engage/callback" in url
        assert "response_type=code" in url
        assert SCOPES.replace(" ", "%20") in url or SCOPES in url


class TestGongEngageExchangeCode:
    @pytest.mark.asyncio
    async def test_exchanges_code_for_tokens(self):
        from services.gong_engage import exchange_code

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "gong-access-token",
            "refresh_token": "gong-refresh-token",
            "expires_in": 7200,
        }
        mock_response.raise_for_status = MagicMock()

        with patch("services.gong_engage.get_settings") as mock_settings, \
             patch("httpx.AsyncClient") as mock_client_cls:
            mock_settings.return_value = MagicMock(
                gong_engage_client_id="cid",
                gong_engage_client_secret="csecret",
                app_url="https://app.example.com",
            )
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await exchange_code("auth-code-gong")

        assert result["access_token"] == "gong-access-token"
        assert result["refresh_token"] == "gong-refresh-token"
        mock_client.post.assert_called_once()
        call_kwargs = mock_client.post.call_args
        assert call_kwargs[1]["data"]["code"] == "auth-code-gong"
        assert call_kwargs[1]["data"]["grant_type"] == "authorization_code"


class TestGongEngageTokenRefresh:
    @pytest.mark.asyncio
    async def test_returns_valid_token_without_refresh(self):
        from services.gong_engage import refresh_access_token

        future = datetime.now(timezone.utc) + timedelta(hours=2)
        with patch("services.gong_engage.get_integration", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {
                "access_token": "still-valid",
                "refresh_token": "rt",
                "token_expires_at": future,
            }
            token = await refresh_access_token(user_id=1)

        assert token == "still-valid"

    @pytest.mark.asyncio
    async def test_refreshes_expired_token(self):
        from services.gong_engage import refresh_access_token

        past = datetime.now(timezone.utc) - timedelta(minutes=10)
        with patch("services.gong_engage.get_integration", new_callable=AsyncMock) as mock_get, \
             patch("services.gong_engage.update_integration_tokens", new_callable=AsyncMock) as mock_update, \
             patch("services.gong_engage.get_settings") as mock_settings, \
             patch("httpx.AsyncClient") as mock_client_cls:

            mock_get.return_value = {
                "access_token": "expired-token",
                "refresh_token": "my-refresh-token",
                "token_expires_at": past,
            }
            mock_settings.return_value = MagicMock(
                gong_engage_client_id="cid",
                gong_engage_client_secret="csecret",
                app_url="https://app.example.com",
            )

            mock_response = MagicMock()
            mock_response.json.return_value = {
                "access_token": "refreshed-token",
                "refresh_token": "new-rt",
                "expires_in": 7200,
            }
            mock_response.raise_for_status = MagicMock()

            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            token = await refresh_access_token(user_id=1)

        assert token == "refreshed-token"
        mock_update.assert_called_once()
        update_kwargs = mock_update.call_args
        assert update_kwargs[1]["access_token"] == "refreshed-token"

    @pytest.mark.asyncio
    async def test_raises_when_not_connected(self):
        from services.gong_engage import refresh_access_token

        with patch("services.gong_engage.get_integration", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = None

            with pytest.raises(RuntimeError, match="Gong Engage not connected"):
                await refresh_access_token(user_id=1)


class TestGongEngageListFlows:
    @pytest.mark.asyncio
    async def test_returns_flows(self):
        from services.gong_engage import list_flows

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "flows": [
                {"id": "flow-1", "name": "Outbound Flow A"},
                {"id": "flow-2", "name": "Follow-Up Flow B"},
            ]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("services.gong_engage.get_valid_token", new_callable=AsyncMock, return_value="token"), \
             patch("httpx.AsyncClient") as mock_client_cls:

            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            flows = await list_flows(user_id=1)

        assert len(flows) == 2
        assert flows[0] == {"id": "flow-1", "name": "Outbound Flow A"}
        assert flows[1] == {"id": "flow-2", "name": "Follow-Up Flow B"}

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_flows(self):
        from services.gong_engage import list_flows

        mock_response = MagicMock()
        mock_response.json.return_value = {"flows": []}
        mock_response.raise_for_status = MagicMock()

        with patch("services.gong_engage.get_valid_token", new_callable=AsyncMock, return_value="token"), \
             patch("httpx.AsyncClient") as mock_client_cls:

            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            flows = await list_flows(user_id=1)

        assert flows == []


class TestGongEngagePushSequences:
    @pytest.mark.asyncio
    async def test_assigns_prospects_to_flow(self):
        from services.gong_engage import push_sequences_to_gong_engage

        accounts = [
            {"id": 1, "company_name": "Acme", "company_url": "https://acme.com"},
            {"id": 2, "company_name": "Beta", "company_url": "https://beta.com"},
        ]
        drafts = {
            1: [
                {"subject": "Subject 1", "body": "Body 1"},
                {"subject": "Subject 2", "body": "Body 2"},
            ],
            2: [
                {"subject": "Subject A", "body": "Body A"},
            ],
        }

        mock_response = MagicMock(status_code=200)

        with patch("services.gong_engage.get_valid_token", new_callable=AsyncMock, return_value="token"), \
             patch("services.gong_engage.update_list_account_pushed", new_callable=AsyncMock) as mock_pushed, \
             patch("httpx.AsyncClient") as mock_client_cls:

            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await push_sequences_to_gong_engage(
                user_id=1, flow_id="flow-1", flow_owner_email="owner@co.com",
                accounts=accounts, drafts_by_account=drafts,
            )

        assert result["prospects_assigned"] == 2
        assert result["skipped"] == 0
        assert result["errors"] == 0
        mock_client.post.assert_called_once()
        call_kwargs = mock_client.post.call_args
        assert call_kwargs[1]["json"]["flowId"] == "flow-1"
        assert call_kwargs[1]["json"]["flowInstanceOwnerEmail"] == "owner@co.com"
        assert len(call_kwargs[1]["json"]["prospects"]) == 2
        assert mock_pushed.call_count == 2

    @pytest.mark.asyncio
    async def test_skips_accounts_without_drafts(self):
        from services.gong_engage import push_sequences_to_gong_engage

        accounts = [
            {"id": 1, "company_name": "Acme", "company_url": "https://acme.com"},
            {"id": 2, "company_name": "Beta", "company_url": "https://beta.com"},
        ]
        drafts = {
            1: [{"subject": "Subject 1", "body": "Body 1"}],
            # account 2 has no drafts
        }

        mock_response = MagicMock(status_code=200)

        with patch("services.gong_engage.get_valid_token", new_callable=AsyncMock, return_value="token"), \
             patch("services.gong_engage.update_list_account_pushed", new_callable=AsyncMock), \
             patch("httpx.AsyncClient") as mock_client_cls:

            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await push_sequences_to_gong_engage(
                user_id=1, flow_id="flow-1", flow_owner_email="owner@co.com",
                accounts=accounts, drafts_by_account=drafts,
            )

        assert result["prospects_assigned"] == 1
        assert result["skipped"] == 1

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_drafts(self):
        from services.gong_engage import push_sequences_to_gong_engage

        accounts = [
            {"id": 1, "company_name": "Acme", "company_url": "https://acme.com"},
        ]

        with patch("services.gong_engage.get_valid_token", new_callable=AsyncMock, return_value="token"):
            result = await push_sequences_to_gong_engage(
                user_id=1, flow_id="flow-1", flow_owner_email="owner@co.com",
                accounts=accounts, drafts_by_account={},
            )

        assert result["prospects_assigned"] == 0
        assert result["skipped"] == 1

    @pytest.mark.asyncio
    async def test_handles_api_error(self):
        from services.gong_engage import push_sequences_to_gong_engage

        accounts = [
            {"id": 1, "company_name": "Acme", "company_url": "https://acme.com"},
        ]
        drafts = {1: [{"subject": "Subj", "body": "Body"}]}

        mock_response = MagicMock(status_code=500, text="Internal Server Error")

        with patch("services.gong_engage.get_valid_token", new_callable=AsyncMock, return_value="token"), \
             patch("httpx.AsyncClient") as mock_client_cls:

            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await push_sequences_to_gong_engage(
                user_id=1, flow_id="flow-1", flow_owner_email="owner@co.com",
                accounts=accounts, drafts_by_account=drafts,
            )

        assert result["errors"] == 1
        assert result["prospects_assigned"] == 0

    @pytest.mark.asyncio
    async def test_handles_network_exception(self):
        from services.gong_engage import push_sequences_to_gong_engage

        accounts = [
            {"id": 1, "company_name": "Acme", "company_url": "https://acme.com"},
        ]
        drafts = {1: [{"subject": "Subj", "body": "Body"}]}

        with patch("services.gong_engage.get_valid_token", new_callable=AsyncMock, return_value="token"), \
             patch("httpx.AsyncClient") as mock_client_cls:

            mock_client = AsyncMock()
            mock_client.post.side_effect = httpx.ConnectError("Connection refused")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await push_sequences_to_gong_engage(
                user_id=1, flow_id="flow-1", flow_owner_email="owner@co.com",
                accounts=accounts, drafts_by_account=drafts,
            )

        assert result["errors"] == 1
        assert result["prospects_assigned"] == 0

    @pytest.mark.asyncio
    async def test_content_overrides_structure(self):
        from services.gong_engage import push_sequences_to_gong_engage

        accounts = [{"id": 1, "company_name": "Acme", "company_url": "https://acme.com"}]
        drafts = {
            1: [
                {"subject": "First Email", "body": "Hello there"},
                {"subject": "Follow Up", "body": "Just checking in"},
            ],
        }

        mock_response = MagicMock(status_code=200)

        with patch("services.gong_engage.get_valid_token", new_callable=AsyncMock, return_value="token"), \
             patch("services.gong_engage.update_list_account_pushed", new_callable=AsyncMock), \
             patch("httpx.AsyncClient") as mock_client_cls:

            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            await push_sequences_to_gong_engage(
                user_id=1, flow_id="flow-1", flow_owner_email="owner@co.com",
                accounts=accounts, drafts_by_account=drafts,
            )

        call_kwargs = mock_client.post.call_args
        prospect = call_kwargs[1]["json"]["prospects"][0]
        overrides = prospect["contentOverrides"]
        assert len(overrides) == 2
        assert overrides[0]["stepIndex"] == 0
        assert overrides[0]["subject"] == "First Email"
        assert "Hello there" in overrides[0]["body"]
        assert overrides[1]["stepIndex"] == 1
        assert overrides[1]["subject"] == "Follow Up"


class TestPlainToHtml:
    def test_escapes_html(self):
        from services.gong_engage import _plain_to_html
        assert "&lt;script&gt;" in _plain_to_html("<script>")

    def test_converts_newlines(self):
        from services.gong_engage import _plain_to_html
        result = _plain_to_html("Hello\n\nWorld")
        assert "</p><p>" in result

    def test_converts_single_newlines_to_br(self):
        from services.gong_engage import _plain_to_html
        result = _plain_to_html("Line 1\nLine 2")
        assert "<br>" in result


# =============================================================================
# Gong Engage Route Tests
# =============================================================================

class TestGongEngageConnectRoute:
    @pytest.mark.asyncio
    async def test_redirects_to_gong(self, authed_client):
        with patch("routes.integrations.gong_engage_authorize_url", return_value="https://app.gong.io/oauth2/authorize?test=1"):
            response = await authed_client.get("/integrations/gong_engage/connect", follow_redirects=False)

        assert response.status_code in (302, 307)
        assert "gong.io" in response.headers.get("location", "")


class TestGongEngageDisconnectRoute:
    @pytest.mark.asyncio
    async def test_disconnect_deletes_integration(self, authed_client):
        with patch("routes.integrations.delete_integration", new_callable=AsyncMock, return_value=True) as mock_delete:
            response = await authed_client.post("/integrations/gong_engage/disconnect", follow_redirects=False)

        assert response.status_code == 303
        mock_delete.assert_called_once_with(1, "gong_engage")


class TestGongEngageFlowsRoute:
    @pytest.mark.asyncio
    async def test_returns_flows(self, authed_client):
        flows = [{"id": "flow-1", "name": "Test Flow"}]
        with patch("services.gong_engage.list_flows", new_callable=AsyncMock, return_value=flows):
            response = await authed_client.get("/integrations/gong_engage/flows")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "Test Flow"

    @pytest.mark.asyncio
    async def test_returns_502_on_error(self, authed_client):
        with patch("services.gong_engage.list_flows", new_callable=AsyncMock, side_effect=RuntimeError("API error")):
            response = await authed_client.get("/integrations/gong_engage/flows")

        assert response.status_code == 502


class TestPushToGongEngageRoute:
    @pytest.mark.asyncio
    async def test_push_succeeds(self, authed_client):
        with patch("database.get_list", new_callable=AsyncMock, return_value={"id": 1, "user_id": 1}), \
             patch("routes.lists.get_list_accounts", new_callable=AsyncMock, return_value=[
                 {"id": 10, "status": "completed", "document_id": 100, "company_name": "Acme", "company_url": "https://acme.com"},
             ]), \
             patch("database.get_outreach_draft", new_callable=AsyncMock, return_value={
                 "content": {"emails": [{"subject": "Hi", "body": "Hello"}]},
             }), \
             patch("routes.lists.push_sequences_to_gong_engage", new_callable=AsyncMock, return_value={
                 "prospects_assigned": 1, "skipped": 0, "errors": 0,
             }) as mock_push:

            response = await authed_client.post(
                "/lists/1/push-gong-engage",
                json={"flow_id": "flow-1", "flow_owner_email": "owner@co.com"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["prospects_assigned"] == 1
        mock_push.assert_called_once()

    @pytest.mark.asyncio
    async def test_push_requires_flow_id(self, authed_client):
        response = await authed_client.post(
            "/lists/1/push-gong-engage",
            json={"flow_owner_email": "owner@co.com"},
        )
        assert response.status_code == 400 or response.status_code == 422

    @pytest.mark.asyncio
    async def test_push_requires_flow_owner_email(self, authed_client):
        response = await authed_client.post(
            "/lists/1/push-gong-engage",
            json={"flow_id": "flow-1"},
        )
        assert response.status_code == 400 or response.status_code == 422

    @pytest.mark.asyncio
    async def test_push_rejects_missing_list(self, authed_client):
        with patch("database.get_list", new_callable=AsyncMock, return_value=None):
            response = await authed_client.post(
                "/lists/1/push-gong-engage",
                json={"flow_id": "flow-1", "flow_owner_email": "owner@co.com"},
            )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_push_rejects_no_sequences(self, authed_client):
        with patch("database.get_list", new_callable=AsyncMock, return_value={"id": 1, "user_id": 1}), \
             patch("routes.lists.get_list_accounts", new_callable=AsyncMock, return_value=[
                 {"id": 10, "status": "completed", "document_id": 100, "company_name": "Acme", "company_url": "https://acme.com"},
             ]), \
             patch("database.get_outreach_draft", new_callable=AsyncMock, return_value=None):

            response = await authed_client.post(
                "/lists/1/push-gong-engage",
                json={"flow_id": "flow-1", "flow_owner_email": "owner@co.com"},
            )

        assert response.status_code == 400
        body = response.json()
        assert "Write sequences first" in (body.get("detail") or body.get("error", {}).get("message", "") or str(body))
