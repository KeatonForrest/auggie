"""
test_new_integrations.py - Tests for Salesforce, Apollo, Ocean.io, Slack/Notifications services and routes.
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch, MagicMock

import httpx


# =============================================================================
# Salesforce Service Tests
# =============================================================================

class TestSalesforceAuthorizeUrl:
    def test_builds_correct_url(self):
        from services.salesforce import get_authorize_url, SALESFORCE_AUTH_URL, SCOPES

        with patch("services.salesforce.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                salesforce_client_id="sf-client-id",
                app_url="https://app.example.com",
            )
            url = get_authorize_url("test-state-456")

        assert url.startswith(SALESFORCE_AUTH_URL)
        assert "client_id=sf-client-id" in url
        assert "state=test-state-456" in url
        assert "redirect_uri=https%3A//app.example.com/integrations/salesforce/callback" in url or \
               "redirect_uri=https://app.example.com/integrations/salesforce/callback" in url
        assert "response_type=code" in url


class TestSalesforceExchangeCode:
    @pytest.mark.asyncio
    async def test_exchanges_code_for_tokens(self):
        from services.salesforce import exchange_code

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "sf-access-token",
            "refresh_token": "sf-refresh-token",
            "instance_url": "https://myorg.salesforce.com",
        }
        mock_response.raise_for_status = MagicMock()

        with patch("services.salesforce.get_settings") as mock_settings, \
             patch("httpx.AsyncClient") as mock_client_cls:
            mock_settings.return_value = MagicMock(
                salesforce_client_id="cid",
                salesforce_client_secret="csecret",
                app_url="https://app.example.com",
            )
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await exchange_code("auth-code-sf")

        assert result["access_token"] == "sf-access-token"
        assert result["instance_url"] == "https://myorg.salesforce.com"
        call_kwargs = mock_client.post.call_args
        assert call_kwargs[1]["data"]["code"] == "auth-code-sf"
        assert call_kwargs[1]["data"]["grant_type"] == "authorization_code"


class TestSalesforceTokenRefresh:
    @pytest.mark.asyncio
    async def test_returns_valid_token_without_refresh(self):
        from services.salesforce import refresh_access_token

        future = datetime.now(timezone.utc) + timedelta(hours=2)
        with patch("services.salesforce.get_integration", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {
                "access_token": "still-valid",
                "refresh_token": "rt",
                "token_expires_at": future,
                "metadata": {"instance_url": "https://myorg.salesforce.com"},
            }
            token, instance_url = await refresh_access_token(user_id=1)

        assert token == "still-valid"
        assert instance_url == "https://myorg.salesforce.com"

    @pytest.mark.asyncio
    async def test_refreshes_expired_token(self):
        from services.salesforce import refresh_access_token

        past = datetime.now(timezone.utc) - timedelta(minutes=10)
        with patch("services.salesforce.get_integration", new_callable=AsyncMock) as mock_get, \
             patch("services.salesforce.update_integration_tokens", new_callable=AsyncMock) as mock_update, \
             patch("services.salesforce.get_settings") as mock_settings, \
             patch("httpx.AsyncClient") as mock_client_cls:

            mock_get.return_value = {
                "access_token": "expired-token",
                "refresh_token": "my-refresh-token",
                "token_expires_at": past,
                "metadata": {"instance_url": "https://myorg.salesforce.com"},
            }
            mock_settings.return_value = MagicMock(
                salesforce_client_id="cid",
                salesforce_client_secret="csecret",
            )

            mock_response = MagicMock()
            mock_response.json.return_value = {
                "access_token": "refreshed-token",
                "instance_url": "https://myorg.salesforce.com",
            }
            mock_response.raise_for_status = MagicMock()

            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            token, instance_url = await refresh_access_token(user_id=1)

        assert token == "refreshed-token"
        mock_update.assert_called_once()

    @pytest.mark.asyncio
    async def test_raises_when_not_connected(self):
        from services.salesforce import refresh_access_token

        with patch("services.salesforce.get_integration", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = None

            with pytest.raises(RuntimeError, match="Salesforce not connected"):
                await refresh_access_token(user_id=1)


class TestSalesforceWriteScores:
    @pytest.mark.asyncio
    async def test_writes_scores_to_account(self):
        from services.salesforce import write_scores_to_salesforce

        mock_patch_resp = MagicMock(status_code=204)
        mock_field_resp = MagicMock(status_code=400)  # Fields already exist

        with patch("services.salesforce.get_valid_token", new_callable=AsyncMock, return_value=("token", "https://myorg.salesforce.com")), \
             patch("httpx.AsyncClient") as mock_client_cls:

            mock_client = AsyncMock()
            mock_client.post.return_value = mock_field_resp
            mock_client.patch.return_value = mock_patch_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await write_scores_to_salesforce(
                user_id=1, sf_account_id="001xx000003ABCD",
                pain_score=85, fit_score=70, timing_score=60, composite_score=74,
            )

        assert result is True

    @pytest.mark.asyncio
    async def test_returns_true_when_no_scores(self):
        from services.salesforce import write_scores_to_salesforce

        with patch("services.salesforce.get_valid_token", new_callable=AsyncMock, return_value=("token", "https://myorg.salesforce.com")), \
             patch("services.salesforce._ensure_custom_fields", new_callable=AsyncMock):

            result = await write_scores_to_salesforce(
                user_id=1, sf_account_id="001xx",
                pain_score=None, fit_score=None, timing_score=None, composite_score=None,
            )

        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_on_api_error(self):
        from services.salesforce import write_scores_to_salesforce

        mock_patch_resp = MagicMock(status_code=500, text="Internal Server Error")

        with patch("services.salesforce.get_valid_token", new_callable=AsyncMock, return_value=("token", "https://myorg.salesforce.com")), \
             patch("services.salesforce._ensure_custom_fields", new_callable=AsyncMock), \
             patch("httpx.AsyncClient") as mock_client_cls:

            mock_client = AsyncMock()
            mock_client.patch.return_value = mock_patch_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await write_scores_to_salesforce(
                user_id=1, sf_account_id="001xx",
                pain_score=85, fit_score=70, timing_score=60, composite_score=74,
            )

        assert result is False


class TestSalesforceWriteListScores:
    @pytest.mark.asyncio
    async def test_writes_scores_for_completed_accounts(self):
        from services.salesforce import write_list_scores_to_salesforce

        source = {
            "provider": "salesforce",
            "salesforce_account_map": {
                "https://acme.com": "001xx1",
                "https://beta.com": "001xx2",
            },
        }
        accounts = [
            {"status": "completed", "company_url": "https://acme.com", "pain_score": 80, "fit_score": 70, "timing_score": 60, "composite_score": 72},
            {"status": "failed", "company_url": "https://beta.com"},
        ]

        with patch("services.salesforce.write_scores_to_salesforce", new_callable=AsyncMock, return_value=True) as mock_write:
            result = await write_list_scores_to_salesforce(user_id=1, list_source=source, accounts=accounts)

        assert result == 1
        mock_write.assert_called_once_with(1, "001xx1", pain_score=80, fit_score=70, timing_score=60, composite_score=72)

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_map(self):
        from services.salesforce import write_list_scores_to_salesforce

        result = await write_list_scores_to_salesforce(user_id=1, list_source={"provider": "salesforce"}, accounts=[])
        assert result == 0


# =============================================================================
# Apollo Integration Service Tests
# =============================================================================

class TestApolloIntegrationValidateKey:
    @pytest.mark.asyncio
    async def test_valid_key_returns_true(self):
        from services.apollo import validate_integration_api_key

        mock_resp = MagicMock(status_code=200)

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            assert await validate_integration_api_key("valid-key") is True

    @pytest.mark.asyncio
    async def test_invalid_key_returns_false(self):
        from services.apollo import validate_integration_api_key

        mock_resp = MagicMock(status_code=401)

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            assert await validate_integration_api_key("bad-key") is False


class TestApolloIntegrationGetKey:
    @pytest.mark.asyncio
    async def test_returns_key_when_connected(self):
        from services.apollo import _get_integration_api_key

        with patch("services.apollo.get_integration", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {"access_token": "apollo-key"}
            key = await _get_integration_api_key(user_id=1)

        assert key == "apollo-key"

    @pytest.mark.asyncio
    async def test_raises_when_not_connected(self):
        from services.apollo import _get_integration_api_key

        with patch("services.apollo.get_integration", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = None

            with pytest.raises(RuntimeError, match="Apollo not connected"):
                await _get_integration_api_key(user_id=1)


class TestApolloListSavedLists:
    @pytest.mark.asyncio
    async def test_returns_labels(self):
        from services.apollo import list_saved_lists

        mock_resp = MagicMock()
        mock_resp.json.return_value = [{"id": "l1", "name": "My List"}]
        mock_resp.raise_for_status = MagicMock()

        with patch("services.apollo._get_integration_api_key", new_callable=AsyncMock, return_value="key"), \
             patch("httpx.AsyncClient") as mock_client_cls:

            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await list_saved_lists(user_id=1)

        assert len(result) == 1
        assert result[0]["name"] == "My List"


class TestApolloFetchListCompanies:
    @pytest.mark.asyncio
    async def test_fetches_companies(self):
        from services.apollo import fetch_list_companies

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "organizations": [{"id": "org1", "primary_domain": "acme.com"}],
            "pagination": {"page": 1, "per_page": 100},
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("services.apollo._get_integration_api_key", new_callable=AsyncMock, return_value="key"), \
             patch("httpx.AsyncClient") as mock_client_cls:

            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await fetch_list_companies(user_id=1, list_id="l1")

        assert len(result["organizations"]) == 1
        # Verify label_ids passed
        call_json = mock_client.post.call_args[1]["json"]
        assert call_json["label_ids"] == ["l1"]


# =============================================================================
# Ocean.io Service Tests
# =============================================================================

class TestOceanValidateApiKey:
    @pytest.mark.asyncio
    async def test_valid_key_returns_true(self):
        from services.ocean import validate_api_key

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
        from services.ocean import validate_api_key

        mock_resp = MagicMock(status_code=401)

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            assert await validate_api_key("bad-key") is False


class TestOceanGetApiKey:
    @pytest.mark.asyncio
    async def test_returns_key_when_connected(self):
        from services.ocean import _get_api_key

        with patch("services.ocean.get_integration", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {"access_token": "ocean-key"}
            key = await _get_api_key(user_id=1)

        assert key == "ocean-key"

    @pytest.mark.asyncio
    async def test_raises_when_not_connected(self):
        from services.ocean import _get_api_key

        with patch("services.ocean.get_integration", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = None

            with pytest.raises(RuntimeError, match="Ocean.io not connected"):
                await _get_api_key(user_id=1)


class TestOceanListAudiences:
    @pytest.mark.asyncio
    async def test_returns_audiences(self):
        from services.ocean import list_audiences

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"audiences": [{"id": "aud1", "name": "Lookalike"}]}
        mock_resp.raise_for_status = MagicMock()

        with patch("services.ocean._get_api_key", new_callable=AsyncMock, return_value="key"), \
             patch("httpx.AsyncClient") as mock_client_cls:

            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await list_audiences(user_id=1)

        assert len(result) == 1
        assert result[0]["name"] == "Lookalike"


class TestOceanFetchAudienceCompanies:
    @pytest.mark.asyncio
    async def test_fetches_companies(self):
        from services.ocean import fetch_audience_companies

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "companies": [{"id": "c1", "domain": "acme.com"}],
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("services.ocean._get_api_key", new_callable=AsyncMock, return_value="key"), \
             patch("httpx.AsyncClient") as mock_client_cls:

            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await fetch_audience_companies(user_id=1, audience_id="aud1")

        assert len(result["companies"]) == 1


# =============================================================================
# Notifications Service Tests
# =============================================================================

class TestFormatSlackMessage:
    def test_research_complete_message(self):
        from services.notifications import format_slack_message

        msg = format_slack_message("research_complete", {
            "company_name": "Acme Corp",
            "pain_score": 85,
            "composite_score": 78,
            "doc_url": "https://app.example.com/document/1",
        })

        assert "blocks" in msg
        header = msg["blocks"][0]
        assert header["type"] == "header"
        assert "Acme Corp" in header["text"]["text"]

    def test_list_complete_message(self):
        from services.notifications import format_slack_message

        msg = format_slack_message("list_complete", {
            "list_name": "My List",
            "total_accounts": 10,
            "completed_accounts": 8,
            "failed_accounts": 2,
        })

        assert "blocks" in msg
        assert "My List" in msg["blocks"][0]["text"]["text"]

    def test_high_pain_alert_message(self):
        from services.notifications import format_slack_message

        msg = format_slack_message("high_pain_alert", {
            "company_name": "BigCo",
            "pain_score": 92,
        })

        assert "blocks" in msg
        assert "BigCo" in msg["blocks"][0]["text"]["text"]
        assert "92" in msg["blocks"][0]["text"]["text"]

    def test_unknown_event_fallback(self):
        from services.notifications import format_slack_message

        msg = format_slack_message("unknown_event", {"foo": "bar"})
        assert "blocks" in msg


class TestSendSlackNotification:
    @pytest.mark.asyncio
    async def test_sends_successfully(self):
        from services.notifications import send_slack_notification

        mock_resp = MagicMock(status_code=200)

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await send_slack_notification(
                "https://hooks.slack.com/test",
                "research_complete",
                {"company_name": "Test"},
            )

        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_on_error(self):
        from services.notifications import send_slack_notification

        mock_resp = MagicMock(status_code=400, text="invalid_payload")

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await send_slack_notification(
                "https://hooks.slack.com/test",
                "research_complete",
                {"company_name": "Test"},
            )

        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_on_exception(self):
        from services.notifications import send_slack_notification

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.side_effect = Exception("network error")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await send_slack_notification(
                "https://hooks.slack.com/test",
                "research_complete",
                {"company_name": "Test"},
            )

        assert result is False


class TestValidateWebhookUrl:
    @pytest.mark.asyncio
    async def test_valid_url_returns_true(self):
        from services.notifications import validate_webhook_url

        mock_resp = MagicMock(status_code=200)

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            assert await validate_webhook_url("https://hooks.slack.com/test") is True

    @pytest.mark.asyncio
    async def test_invalid_url_returns_false(self):
        from services.notifications import validate_webhook_url

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.side_effect = Exception("connection refused")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            assert await validate_webhook_url("https://bad-url.example.com") is False


# =============================================================================
# Route Tests: Salesforce
# =============================================================================

class TestSalesforceConnectRoute:
    @pytest.mark.asyncio
    async def test_redirects_to_salesforce(self, authed_client):
        with patch("routes.integrations.salesforce_authorize_url", return_value="https://login.salesforce.com/services/oauth2/authorize?test=1"):
            response = await authed_client.get("/integrations/salesforce/connect", follow_redirects=False)

        assert response.status_code in (302, 307)
        assert "salesforce.com" in response.headers.get("location", "")


class TestSalesforceDisconnectRoute:
    @pytest.mark.asyncio
    async def test_disconnect_deletes_integration(self, authed_client):
        with patch("routes.integrations.delete_integration", new_callable=AsyncMock, return_value=True) as mock_delete:
            response = await authed_client.post("/integrations/salesforce/disconnect", follow_redirects=False)

        assert response.status_code == 303
        mock_delete.assert_called_once_with(1, "salesforce")


class TestSalesforceImportRoute:
    @pytest.mark.asyncio
    async def test_import_creates_list(self, authed_client):
        with patch("routes._helpers.get_user_usage", new_callable=AsyncMock, return_value={"bonus_credits": 10000, "is_admin": False}), \
             patch("routes._helpers.use_credit", new_callable=AsyncMock, return_value=True), \
             patch("routes._helpers.create_list", new_callable=AsyncMock, return_value={"id": 55}), \
             patch("routes._helpers.add_list_accounts", new_callable=AsyncMock), \
             patch("routes._helpers.update_list_credits", new_callable=AsyncMock), \
             patch("database.set_list_source", new_callable=AsyncMock) as mock_source, \
             patch("routes._helpers.create_tracked_task", new_callable=AsyncMock):

            response = await authed_client.post(
                "/integrations/salesforce/import",
                json={
                    "accounts": [
                        {"id": "001xx1", "website": "acme.com"},
                        {"id": "001xx2", "website": "beta.com"},
                    ],
                    "name": "SF Import",
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["list_id"] == 55
        mock_source.assert_called_once()
        source_arg = mock_source.call_args[0][1]
        assert source_arg["provider"] == "salesforce"
        assert "https://acme.com" in source_arg["salesforce_account_map"]

    @pytest.mark.asyncio
    async def test_import_rejects_empty_accounts(self, authed_client):
        response = await authed_client.post(
            "/integrations/salesforce/import",
            json={"accounts": [], "name": "Empty"},
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_import_rejects_insufficient_credits(self, authed_client):
        with patch("routes._helpers.get_user_usage", new_callable=AsyncMock, return_value={"bonus_credits": 0, "is_admin": False}):
            response = await authed_client.post(
                "/integrations/salesforce/import",
                json={"accounts": [{"id": "001xx1", "website": "acme.com"}], "name": "Test"},
            )
        assert response.status_code == 402


# =============================================================================
# Route Tests: Apollo
# =============================================================================

class TestApolloConnectRoute:
    @pytest.mark.asyncio
    async def test_valid_key_connects(self, authed_client):
        with patch("routes.integrations.apollo_validate", new_callable=AsyncMock, return_value=True), \
             patch("routes._helpers.upsert_integration", new_callable=AsyncMock) as mock_upsert:

            response = await authed_client.post(
                "/integrations/apollo/connect",
                json={"api_key": "apollo-key-123"},
            )

        assert response.status_code == 200
        assert response.json()["success"] is True
        mock_upsert.assert_called_once()

    @pytest.mark.asyncio
    async def test_invalid_key_rejected(self, authed_client):
        with patch("routes.integrations.apollo_validate", new_callable=AsyncMock, return_value=False):
            response = await authed_client.post(
                "/integrations/apollo/connect",
                json={"api_key": "bad-key"},
            )

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_empty_key_rejected(self, authed_client):
        response = await authed_client.post(
            "/integrations/apollo/connect",
            json={"api_key": ""},
        )
        assert response.status_code == 400


class TestApolloDisconnectRoute:
    @pytest.mark.asyncio
    async def test_disconnect(self, authed_client):
        with patch("routes.integrations.delete_integration", new_callable=AsyncMock, return_value=True) as mock_delete:
            response = await authed_client.post("/integrations/apollo/disconnect", follow_redirects=False)

        assert response.status_code == 303
        mock_delete.assert_called_once_with(1, "apollo")


class TestApolloImportRoute:
    @pytest.mark.asyncio
    async def test_import_creates_list(self, authed_client):
        with patch("services.apollo.fetch_list_companies", new_callable=AsyncMock, return_value={
                 "organizations": [
                     {"id": "org1", "primary_domain": "acme.com"},
                     {"id": "org2", "primary_domain": "beta.com"},
                 ],
             }), \
             patch("routes._helpers.get_user_usage", new_callable=AsyncMock, return_value={"bonus_credits": 10000, "is_admin": False}), \
             patch("routes._helpers.use_credit", new_callable=AsyncMock, return_value=True), \
             patch("routes._helpers.create_list", new_callable=AsyncMock, return_value={"id": 60}), \
             patch("routes._helpers.add_list_accounts", new_callable=AsyncMock), \
             patch("routes._helpers.update_list_credits", new_callable=AsyncMock), \
             patch("database.set_list_source", new_callable=AsyncMock) as mock_source, \
             patch("routes._helpers.create_tracked_task", new_callable=AsyncMock):

            response = await authed_client.post(
                "/integrations/apollo/import",
                json={"list_id": "l1", "name": "Apollo Import"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["list_id"] == 60
        mock_source.assert_called_once()
        source_arg = mock_source.call_args[0][1]
        assert source_arg["provider"] == "apollo"
        assert "https://acme.com" in source_arg["org_ids"]

    @pytest.mark.asyncio
    async def test_import_requires_list_id(self, authed_client):
        response = await authed_client.post(
            "/integrations/apollo/import",
            json={"name": "Test"},
        )
        assert response.status_code == 400


# =============================================================================
# Route Tests: Ocean.io
# =============================================================================

class TestOceanConnectRoute:
    @pytest.mark.asyncio
    async def test_valid_key_connects(self, authed_client):
        with patch("routes.integrations.ocean_validate", new_callable=AsyncMock, return_value=True), \
             patch("routes._helpers.upsert_integration", new_callable=AsyncMock) as mock_upsert:

            response = await authed_client.post(
                "/integrations/ocean/connect",
                json={"api_key": "ocean-key-123"},
            )

        assert response.status_code == 200
        assert response.json()["success"] is True
        mock_upsert.assert_called_once()

    @pytest.mark.asyncio
    async def test_invalid_key_rejected(self, authed_client):
        with patch("routes.integrations.ocean_validate", new_callable=AsyncMock, return_value=False):
            response = await authed_client.post(
                "/integrations/ocean/connect",
                json={"api_key": "bad-key"},
            )

        assert response.status_code == 400


class TestOceanDisconnectRoute:
    @pytest.mark.asyncio
    async def test_disconnect(self, authed_client):
        with patch("routes.integrations.delete_integration", new_callable=AsyncMock, return_value=True) as mock_delete:
            response = await authed_client.post("/integrations/ocean/disconnect", follow_redirects=False)

        assert response.status_code == 303
        mock_delete.assert_called_once_with(1, "ocean")


class TestOceanImportRoute:
    @pytest.mark.asyncio
    async def test_import_creates_list(self, authed_client):
        with patch("services.ocean.fetch_audience_companies", new_callable=AsyncMock, return_value={
                 "companies": [
                     {"id": "c1", "domain": "acme.com"},
                     {"id": "c2", "domain": "beta.com"},
                 ],
             }), \
             patch("routes._helpers.get_user_usage", new_callable=AsyncMock, return_value={"bonus_credits": 10000, "is_admin": False}), \
             patch("routes._helpers.use_credit", new_callable=AsyncMock, return_value=True), \
             patch("routes._helpers.create_list", new_callable=AsyncMock, return_value={"id": 70}), \
             patch("routes._helpers.add_list_accounts", new_callable=AsyncMock), \
             patch("routes._helpers.update_list_credits", new_callable=AsyncMock), \
             patch("routes._helpers.create_tracked_task", new_callable=AsyncMock):

            response = await authed_client.post(
                "/integrations/ocean/import",
                json={"audience_id": "aud1", "name": "Ocean Import"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["list_id"] == 70

    @pytest.mark.asyncio
    async def test_import_requires_audience_id(self, authed_client):
        response = await authed_client.post(
            "/integrations/ocean/import",
            json={"name": "Test"},
        )
        assert response.status_code == 400


# =============================================================================
# Route Tests: Slack
# =============================================================================

class TestSlackConnectRoute:
    @pytest.mark.asyncio
    async def test_valid_webhook_connects(self, authed_client):
        with patch("routes.integrations.validate_webhook_url", new_callable=AsyncMock, return_value=True), \
             patch("routes.integrations.upsert_integration", new_callable=AsyncMock) as mock_upsert:

            response = await authed_client.post(
                "/integrations/slack/connect",
                json={"webhook_url": "https://hooks.slack.com/services/T00/B00/xxx"},
            )

        assert response.status_code == 200
        assert response.json()["success"] is True
        mock_upsert.assert_called_once()

    @pytest.mark.asyncio
    async def test_invalid_webhook_rejected(self, authed_client):
        with patch("routes.integrations.validate_webhook_url", new_callable=AsyncMock, return_value=False):
            response = await authed_client.post(
                "/integrations/slack/connect",
                json={"webhook_url": "https://bad-url.com"},
            )

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_empty_url_rejected(self, authed_client):
        response = await authed_client.post(
            "/integrations/slack/connect",
            json={"webhook_url": ""},
        )
        assert response.status_code == 400


class TestSlackDisconnectRoute:
    @pytest.mark.asyncio
    async def test_disconnect(self, authed_client):
        with patch("routes.integrations.delete_integration", new_callable=AsyncMock, return_value=True) as mock_delete:
            response = await authed_client.post("/integrations/slack/disconnect", follow_redirects=False)

        assert response.status_code == 303
        mock_delete.assert_called_once_with(1, "slack")


class TestSlackTestRoute:
    @pytest.mark.asyncio
    async def test_sends_test_message(self, authed_client):
        with patch("routes.integrations.get_integration", new_callable=AsyncMock, return_value={"access_token": "https://hooks.slack.com/test"}), \
             patch("routes.integrations.send_slack_notification", new_callable=AsyncMock, return_value=True):

            response = await authed_client.post("/integrations/slack/test")

        assert response.status_code == 200
        assert response.json()["success"] is True

    @pytest.mark.asyncio
    async def test_fails_when_not_connected(self, authed_client):
        with patch("routes.integrations.get_integration", new_callable=AsyncMock, return_value=None):
            response = await authed_client.post("/integrations/slack/test")

        assert response.status_code == 400


# =============================================================================
# Integrations Page Tests (extended)
# =============================================================================

class TestIntegrationsPageNewProviders:
    @pytest.mark.asyncio
    async def test_page_shows_new_providers(self, authed_client):
        with patch("routes.integrations.get_user_integrations", new_callable=AsyncMock, return_value=[]), \
             patch("routes.integrations.get_user_usage", new_callable=AsyncMock, return_value={"bonus_credits": 1000, "is_admin": False}):

            response = await authed_client.get("/integrations")

        assert response.status_code == 200
        assert "Salesforce" in response.text
        assert "Apollo" in response.text
        assert "Ocean.io" in response.text
        assert "Slack" in response.text

    @pytest.mark.asyncio
    async def test_page_shows_connected_for_new_providers(self, authed_client):
        integrations = [
            {"provider": "salesforce", "access_token": "tok", "created_at": datetime.now(), "updated_at": datetime.now()},
            {"provider": "slack", "access_token": "url", "created_at": datetime.now(), "updated_at": datetime.now()},
        ]
        with patch("routes.integrations.get_user_integrations", new_callable=AsyncMock, return_value=integrations), \
             patch("routes.integrations.get_user_usage", new_callable=AsyncMock, return_value={"bonus_credits": 1000, "is_admin": False}):

            response = await authed_client.get("/integrations")

        assert response.status_code == 200
        assert "Connected" in response.text
