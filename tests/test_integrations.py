"""
test_integrations.py - Tests for HubSpot and Instantly integration services and routes.
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch, MagicMock

import httpx


# =============================================================================
# HubSpot Service Tests
# =============================================================================

class TestHubSpotAuthorizeUrl:
    def test_builds_correct_url(self):
        from services.hubspot import get_authorize_url, HUBSPOT_AUTH_URL, SCOPES

        with patch("services.hubspot.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                hubspot_client_id="test-client-id",
                app_url="https://app.example.com",
            )
            url = get_authorize_url("test-state-123")

        assert url.startswith(HUBSPOT_AUTH_URL)
        assert "client_id=test-client-id" in url
        assert "state=test-state-123" in url
        assert "redirect_uri=https%3A//app.example.com/integrations/hubspot/callback" in url or \
               "redirect_uri=https://app.example.com/integrations/hubspot/callback" in url
        assert SCOPES.replace(" ", "%20") in url or SCOPES in url


class TestHubSpotExchangeCode:
    @pytest.mark.asyncio
    async def test_exchanges_code_for_tokens(self):
        from services.hubspot import exchange_code

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "new-access-token",
            "refresh_token": "new-refresh-token",
            "expires_in": 21600,
        }
        mock_response.raise_for_status = MagicMock()

        with patch("services.hubspot.get_settings") as mock_settings, \
             patch("httpx.AsyncClient") as mock_client_cls:
            mock_settings.return_value = MagicMock(
                hubspot_client_id="cid",
                hubspot_client_secret="csecret",
                app_url="https://app.example.com",
            )
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await exchange_code("auth-code-123")

        assert result["access_token"] == "new-access-token"
        assert result["refresh_token"] == "new-refresh-token"
        mock_client.post.assert_called_once()
        call_kwargs = mock_client.post.call_args
        assert call_kwargs[1]["data"]["code"] == "auth-code-123"
        assert call_kwargs[1]["data"]["grant_type"] == "authorization_code"


class TestHubSpotTokenRefresh:
    @pytest.mark.asyncio
    async def test_returns_valid_token_without_refresh(self):
        from services.hubspot import refresh_access_token

        future = datetime.now(timezone.utc) + timedelta(hours=2)
        with patch("services.hubspot.get_integration", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {
                "access_token": "still-valid",
                "refresh_token": "rt",
                "token_expires_at": future,
            }
            token = await refresh_access_token(user_id=1)

        assert token == "still-valid"

    @pytest.mark.asyncio
    async def test_refreshes_expired_token(self):
        from services.hubspot import refresh_access_token

        past = datetime.now(timezone.utc) - timedelta(minutes=10)
        with patch("services.hubspot.get_integration", new_callable=AsyncMock) as mock_get, \
             patch("services.hubspot.update_integration_tokens", new_callable=AsyncMock) as mock_update, \
             patch("services.hubspot.get_settings") as mock_settings, \
             patch("httpx.AsyncClient") as mock_client_cls:

            mock_get.return_value = {
                "access_token": "expired-token",
                "refresh_token": "my-refresh-token",
                "token_expires_at": past,
            }
            mock_settings.return_value = MagicMock(
                hubspot_client_id="cid",
                hubspot_client_secret="csecret",
            )

            mock_response = MagicMock()
            mock_response.json.return_value = {
                "access_token": "refreshed-token",
                "refresh_token": "new-rt",
                "expires_in": 21600,
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
        from services.hubspot import refresh_access_token

        with patch("services.hubspot.get_integration", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = None

            with pytest.raises(RuntimeError, match="HubSpot not connected"):
                await refresh_access_token(user_id=1)


class TestHubSpotWriteScores:
    @pytest.mark.asyncio
    async def test_writes_scores_to_company(self):
        from services.hubspot import write_scores_to_hubspot

        mock_patch_resp = MagicMock(status_code=200)
        mock_prop_resp = MagicMock(status_code=409)  # Properties already exist

        with patch("services.hubspot.get_valid_token", new_callable=AsyncMock, return_value="token"), \
             patch("httpx.AsyncClient") as mock_client_cls:

            mock_client = AsyncMock()
            mock_client.post.return_value = mock_prop_resp
            mock_client.patch.return_value = mock_patch_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await write_scores_to_hubspot(
                user_id=1, hubspot_company_id="hs-123",
                pain_score=85, fit_score=70, timing_score=60, composite_score=74,
            )

        assert result is True

    @pytest.mark.asyncio
    async def test_returns_true_when_no_scores(self):
        from services.hubspot import write_scores_to_hubspot

        with patch("services.hubspot.get_valid_token", new_callable=AsyncMock, return_value="token"), \
             patch("services.hubspot._ensure_custom_properties", new_callable=AsyncMock):

            result = await write_scores_to_hubspot(
                user_id=1, hubspot_company_id="hs-123",
                pain_score=None, fit_score=None, timing_score=None, composite_score=None,
            )

        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_on_api_error(self):
        from services.hubspot import write_scores_to_hubspot

        mock_patch_resp = MagicMock(status_code=500, text="Internal Server Error")

        with patch("services.hubspot.get_valid_token", new_callable=AsyncMock, return_value="token"), \
             patch("services.hubspot._ensure_custom_properties", new_callable=AsyncMock), \
             patch("httpx.AsyncClient") as mock_client_cls:

            mock_client = AsyncMock()
            mock_client.patch.return_value = mock_patch_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await write_scores_to_hubspot(
                user_id=1, hubspot_company_id="hs-123",
                pain_score=85, fit_score=70, timing_score=60, composite_score=74,
            )

        assert result is False


class TestHubSpotWriteListScores:
    @pytest.mark.asyncio
    async def test_writes_scores_for_completed_accounts(self):
        from services.hubspot import write_list_scores_to_hubspot

        source = {
            "provider": "hubspot",
            "hubspot_company_map": {
                "https://acme.com": "hs-1",
                "https://beta.com": "hs-2",
            },
        }
        accounts = [
            {"status": "completed", "company_url": "https://acme.com", "pain_score": 80, "fit_score": 70, "timing_score": 60, "composite_score": 72},
            {"status": "failed", "company_url": "https://beta.com", "pain_score": None, "fit_score": None, "timing_score": None, "composite_score": None},
        ]

        with patch("services.hubspot.write_scores_to_hubspot", new_callable=AsyncMock, return_value=True) as mock_write:
            result = await write_list_scores_to_hubspot(user_id=1, list_source=source, accounts=accounts)

        assert result == 1
        mock_write.assert_called_once_with(1, "hs-1", pain_score=80, fit_score=70, timing_score=60, composite_score=72)

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_map(self):
        from services.hubspot import write_list_scores_to_hubspot

        result = await write_list_scores_to_hubspot(user_id=1, list_source={"provider": "hubspot"}, accounts=[])
        assert result == 0

    @pytest.mark.asyncio
    async def test_skips_accounts_without_hubspot_id(self):
        from services.hubspot import write_list_scores_to_hubspot

        source = {"provider": "hubspot", "hubspot_company_map": {"https://acme.com": "hs-1"}}
        accounts = [
            {"status": "completed", "company_url": "https://unknown.com", "pain_score": 80, "fit_score": 70, "timing_score": 60, "composite_score": 72},
        ]

        with patch("services.hubspot.write_scores_to_hubspot", new_callable=AsyncMock) as mock_write:
            result = await write_list_scores_to_hubspot(user_id=1, list_source=source, accounts=accounts)

        assert result == 0
        mock_write.assert_not_called()


# =============================================================================
# Instantly Service Tests
# =============================================================================

class TestInstantlyValidateApiKey:
    @pytest.mark.asyncio
    async def test_valid_key_returns_true(self):
        from services.instantly import validate_api_key

        mock_resp = MagicMock(status_code=200)

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            assert await validate_api_key("valid-key") is True

    @pytest.mark.asyncio
    async def test_invalid_key_returns_false(self):
        from services.instantly import validate_api_key

        mock_resp = MagicMock(status_code=401)

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            assert await validate_api_key("bad-key") is False


class TestInstantlyGetApiKey:
    @pytest.mark.asyncio
    async def test_returns_key_when_connected(self):
        from services.instantly import _get_api_key

        with patch("services.instantly.get_integration", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {"access_token": "my-api-key"}
            key = await _get_api_key(user_id=1)

        assert key == "my-api-key"

    @pytest.mark.asyncio
    async def test_raises_when_not_connected(self):
        from services.instantly import _get_api_key

        with patch("services.instantly.get_integration", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = None

            with pytest.raises(RuntimeError, match="Instantly not connected"):
                await _get_api_key(user_id=1)


class TestInstantlyPushAccounts:
    @pytest.mark.asyncio
    async def test_pushes_leads_with_contacts(self):
        from services.instantly import push_accounts_to_instantly

        accounts = [
            {"id": 1, "company_name": "Acme", "company_url": "https://acme.com", "pain_score": 80, "fit_score": 70, "composite_score": 75},
            {"id": 2, "company_name": "Beta", "company_url": "https://beta.com", "pain_score": 60, "fit_score": 50, "composite_score": 55},
        ]
        contacts = {
            1: [
                {"email": "john@acme.com", "first_name": "John", "last_name": "Doe", "title": "CEO"},
                {"email": "jane@acme.com", "first_name": "Jane", "last_name": "Smith", "title": "CTO"},
            ],
            2: [
                {"email": "bob@beta.com", "first_name": "Bob", "last_name": "Jones", "title": "VP Sales"},
            ],
        }

        with patch("services.instantly.add_leads_to_campaign", new_callable=AsyncMock, return_value={"status": "ok"}) as mock_add, \
             patch("services.instantly.update_list_account_pushed", new_callable=AsyncMock) as mock_push:

            result = await push_accounts_to_instantly(
                user_id=1, campaign_id="camp-1", accounts=accounts, contacts_by_account=contacts,
            )

        assert result["pushed"] == 3
        assert result["errors"] == 0
        mock_add.assert_called_once()
        # add_leads_to_campaign is called with positional args
        leads_arg = mock_add.call_args[0][2]  # (user_id, campaign_id, leads)
        assert len(leads_arg) == 3
        assert leads_arg[0]["email"] == "john@acme.com"
        assert leads_arg[0]["company_name"] == "Acme"
        assert leads_arg[0]["custom_variables"]["pain_score"] == "80"
        # Both accounts should be marked as pushed
        assert mock_push.call_count == 2

    @pytest.mark.asyncio
    async def test_skips_accounts_without_contacts(self):
        from services.instantly import push_accounts_to_instantly

        accounts = [
            {"id": 1, "company_name": "Acme", "company_url": "https://acme.com", "pain_score": 80, "fit_score": 70, "composite_score": 75},
        ]
        contacts = {}  # No contacts

        result = await push_accounts_to_instantly(
            user_id=1, campaign_id="camp-1", accounts=accounts, contacts_by_account=contacts,
        )

        assert result["pushed"] == 0
        assert result["skipped"] == 1

    @pytest.mark.asyncio
    async def test_skips_contacts_without_email(self):
        from services.instantly import push_accounts_to_instantly

        accounts = [{"id": 1, "company_name": "Acme", "company_url": "https://acme.com", "pain_score": 80, "fit_score": 70, "composite_score": 75}]
        contacts = {1: [{"first_name": "John", "last_name": "Doe", "title": "CEO"}]}  # No email

        result = await push_accounts_to_instantly(
            user_id=1, campaign_id="camp-1", accounts=accounts, contacts_by_account=contacts,
        )

        assert result["pushed"] == 0
        assert result["skipped"] == 1

    @pytest.mark.asyncio
    async def test_handles_api_error_gracefully(self):
        from services.instantly import push_accounts_to_instantly

        accounts = [{"id": 1, "company_name": "Acme", "company_url": "https://acme.com", "pain_score": 80, "fit_score": 70, "composite_score": 75}]
        contacts = {1: [{"email": "john@acme.com", "first_name": "John", "last_name": "Doe", "title": "CEO"}]}

        with patch("services.instantly.add_leads_to_campaign", new_callable=AsyncMock, side_effect=httpx.HTTPStatusError("fail", request=MagicMock(), response=MagicMock())):
            result = await push_accounts_to_instantly(
                user_id=1, campaign_id="camp-1", accounts=accounts, contacts_by_account=contacts,
            )

        assert result["errors"] == 1
        assert result["pushed"] == 0
        assert "error" in result


# =============================================================================
# Integration Route Tests
# =============================================================================

class TestIntegrationsPage:
    @pytest.mark.asyncio
    async def test_integrations_page_loads(self, authed_client):
        with patch("routes.integrations.get_user_integrations", new_callable=AsyncMock, return_value=[]), \
             patch("routes.integrations.get_user_usage", new_callable=AsyncMock, return_value={"bonus_credits": 1000, "is_admin": False}):

            response = await authed_client.get("/integrations")

        assert response.status_code == 200
        assert "HubSpot" in response.text
        assert "Instantly" in response.text

    @pytest.mark.asyncio
    async def test_shows_connected_status(self, authed_client):
        integrations = [
            {"provider": "hubspot", "access_token": "tok", "created_at": datetime.now(), "updated_at": datetime.now()},
        ]
        with patch("routes.integrations.get_user_integrations", new_callable=AsyncMock, return_value=integrations), \
             patch("routes.integrations.get_user_usage", new_callable=AsyncMock, return_value={"bonus_credits": 1000, "is_admin": False}):

            response = await authed_client.get("/integrations")

        assert response.status_code == 200
        assert "Connected" in response.text


class TestHubSpotConnectRoute:
    @pytest.mark.asyncio
    async def test_redirects_to_hubspot(self, authed_client):
        with patch("routes.integrations.hubspot_authorize_url", return_value="https://app.hubspot.com/oauth/authorize?test=1"):
            response = await authed_client.get("/integrations/hubspot/connect", follow_redirects=False)

        assert response.status_code in (302, 307)
        assert "hubspot.com" in response.headers.get("location", "")


class TestHubSpotDisconnectRoute:
    @pytest.mark.asyncio
    async def test_disconnect_deletes_integration(self, authed_client):
        with patch("routes.integrations.delete_integration", new_callable=AsyncMock, return_value=True) as mock_delete:
            response = await authed_client.post("/integrations/hubspot/disconnect", follow_redirects=False)

        assert response.status_code == 303
        mock_delete.assert_called_once_with(1, "hubspot")


class TestInstantlyConnectRoute:
    @pytest.mark.asyncio
    async def test_valid_key_connects(self, authed_client):
        with patch("routes.integrations.instantly_validate", new_callable=AsyncMock, return_value=True), \
             patch("routes._helpers.upsert_integration", new_callable=AsyncMock) as mock_upsert:

            response = await authed_client.post(
                "/integrations/instantly/connect",
                json={"api_key": "test-key-123"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        mock_upsert.assert_called_once()

    @pytest.mark.asyncio
    async def test_invalid_key_rejected(self, authed_client):
        with patch("routes.integrations.instantly_validate", new_callable=AsyncMock, return_value=False):
            response = await authed_client.post(
                "/integrations/instantly/connect",
                json={"api_key": "bad-key"},
            )

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_empty_key_rejected(self, authed_client):
        response = await authed_client.post(
            "/integrations/instantly/connect",
            json={"api_key": ""},
        )
        assert response.status_code == 400


class TestHubSpotImportRoute:
    @pytest.mark.asyncio
    async def test_import_creates_list(self, authed_client):
        with patch("routes._helpers.get_user_usage", new_callable=AsyncMock, return_value={"bonus_credits": 10000, "is_admin": False}), \
             patch("routes._helpers.use_credit", new_callable=AsyncMock, return_value=True), \
             patch("routes._helpers.create_list", new_callable=AsyncMock, return_value={"id": 42}), \
             patch("routes._helpers.add_list_accounts", new_callable=AsyncMock), \
             patch("routes._helpers.update_list_credits", new_callable=AsyncMock), \
             patch("database.set_list_source", new_callable=AsyncMock) as mock_source, \
             patch("routes._helpers.create_tracked_task", new_callable=AsyncMock):

            response = await authed_client.post(
                "/integrations/hubspot/import",
                json={
                    "companies": [
                        {"id": "hs-1", "domain": "acme.com"},
                        {"id": "hs-2", "domain": "beta.com"},
                    ],
                    "name": "Test Import",
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["list_id"] == 42
        mock_source.assert_called_once()
        source_arg = mock_source.call_args[0][1]
        assert source_arg["provider"] == "hubspot"
        assert "https://acme.com" in source_arg["hubspot_company_map"]

    @pytest.mark.asyncio
    async def test_import_rejects_empty_companies(self, authed_client):
        response = await authed_client.post(
            "/integrations/hubspot/import",
            json={"companies": [], "name": "Empty"},
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_import_rejects_insufficient_credits(self, authed_client):
        with patch("routes._helpers.get_user_usage", new_callable=AsyncMock, return_value={"bonus_credits": 0, "is_admin": False}):
            response = await authed_client.post(
                "/integrations/hubspot/import",
                json={
                    "companies": [{"id": "hs-1", "domain": "acme.com"}],
                    "name": "Test",
                },
            )
        assert response.status_code == 402


class TestPushToInstantlyRoute:
    @pytest.mark.asyncio
    async def test_push_succeeds(self, authed_client):
        with patch("database.get_list", new_callable=AsyncMock, return_value={"id": 1, "user_id": 1}), \
             patch("routes._helpers.get_list_accounts", new_callable=AsyncMock, return_value=[
                 {"id": 10, "status": "completed", "document_id": 100, "company_name": "Acme", "company_url": "https://acme.com"},
             ]), \
             patch("routes._helpers.get_enriched_contacts", new_callable=AsyncMock, return_value=[
                 {"email": "john@acme.com", "first_name": "John", "last_name": "Doe", "title": "CEO"},
             ]), \
             patch("routes.lists.push_accounts_to_instantly", new_callable=AsyncMock, return_value={"pushed": 1, "skipped": 0, "errors": 0}) as mock_push:

            response = await authed_client.post(
                "/lists/1/push-instantly",
                json={"campaign_id": "camp-1"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["pushed"] == 1
        mock_push.assert_called_once()

    @pytest.mark.asyncio
    async def test_push_requires_campaign_id(self, authed_client):
        response = await authed_client.post(
            "/lists/1/push-instantly",
            json={},
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_push_rejects_wrong_user(self, authed_client):
        with patch("database.get_list", new_callable=AsyncMock, return_value=None):
            response = await authed_client.post(
                "/lists/1/push-instantly",
                json={"campaign_id": "camp-1"},
            )
        assert response.status_code == 404
