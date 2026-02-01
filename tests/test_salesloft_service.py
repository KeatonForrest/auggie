"""
test_salesloft_service.py - Tests for SalesLoft integration service.
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch, MagicMock


class TestSalesLoftAuthorizeUrl:
    def test_builds_correct_url(self):
        from services.salesloft import get_authorize_url, SALESLOFT_AUTH_URL

        with patch("services.salesloft.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                salesloft_client_id="sl-client",
                app_url="https://app.example.com",
            )
            url = get_authorize_url("state-sl")

        assert url.startswith(SALESLOFT_AUTH_URL)
        assert "client_id=sl-client" in url
        assert "state=state-sl" in url
        assert "response_type=code" in url


class TestSalesLoftExchangeCode:
    @pytest.mark.asyncio
    async def test_exchanges_code(self):
        from services.salesloft import exchange_code

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"access_token": "sl-token", "refresh_token": "sl-rt", "expires_in": 7200}
        mock_resp.raise_for_status = MagicMock()

        with patch("services.salesloft.get_settings") as mock_settings, \
             patch("httpx.AsyncClient") as mock_cls:
            mock_settings.return_value = MagicMock(
                salesloft_client_id="cid", salesloft_client_secret="csecret",
                app_url="https://app.example.com",
            )
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await exchange_code("auth-code-sl")

        assert result["access_token"] == "sl-token"
        call_data = mock_client.post.call_args[1]["data"]
        assert call_data["code"] == "auth-code-sl"
        assert call_data["grant_type"] == "authorization_code"


class TestSalesLoftTokenRefresh:
    @pytest.mark.asyncio
    async def test_returns_valid_token(self):
        from services.salesloft import refresh_access_token

        future = datetime.now(timezone.utc) + timedelta(hours=2)
        with patch("services.salesloft.get_integration", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {"access_token": "valid", "refresh_token": "rt", "token_expires_at": future}
            token = await refresh_access_token(1)

        assert token == "valid"

    @pytest.mark.asyncio
    async def test_refreshes_expired_token(self):
        from services.salesloft import refresh_access_token

        past = datetime.now(timezone.utc) - timedelta(minutes=10)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"access_token": "new-token", "refresh_token": "new-rt", "expires_in": 7200}
        mock_resp.raise_for_status = MagicMock()

        with patch("services.salesloft.get_integration", new_callable=AsyncMock) as mock_get, \
             patch("services.salesloft.update_integration_tokens", new_callable=AsyncMock) as mock_update, \
             patch("services.salesloft.get_settings") as mock_settings, \
             patch("httpx.AsyncClient") as mock_cls:
            mock_get.return_value = {"access_token": "expired", "refresh_token": "old-rt", "token_expires_at": past}
            mock_settings.return_value = MagicMock(salesloft_client_id="cid", salesloft_client_secret="csecret")
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            token = await refresh_access_token(1)

        assert token == "new-token"
        mock_update.assert_called_once()
        assert mock_update.call_args[1]["access_token"] == "new-token"

    @pytest.mark.asyncio
    async def test_raises_when_not_connected(self):
        from services.salesloft import refresh_access_token

        with patch("services.salesloft.get_integration", new_callable=AsyncMock, return_value=None):
            with pytest.raises(RuntimeError, match="SalesLoft not connected"):
                await refresh_access_token(1)


class TestSalesLoftListCadences:
    @pytest.mark.asyncio
    async def test_returns_cadences(self):
        from services.salesloft import list_cadences

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "data": [
                {"id": 1, "name": "Cadence A"},
                {"id": 2, "name": "Cadence B"},
            ]
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("services.salesloft.get_valid_token", new_callable=AsyncMock, return_value="token"), \
             patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            cadences = await list_cadences(1)

        assert len(cadences) == 2
        assert cadences[0] == {"id": 1, "name": "Cadence A"}

    @pytest.mark.asyncio
    async def test_returns_empty(self):
        from services.salesloft import list_cadences

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": []}
        mock_resp.raise_for_status = MagicMock()

        with patch("services.salesloft.get_valid_token", new_callable=AsyncMock, return_value="token"), \
             patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            cadences = await list_cadences(1)

        assert cadences == []


class TestSalesLoftCreateCadence:
    @pytest.mark.asyncio
    async def test_creates_cadence_with_steps(self):
        from services.salesloft import _create_cadence_with_emails

        cadence_resp = MagicMock(status_code=200)
        cadence_resp.json.return_value = {"data": {"id": 42}}
        step_resp = MagicMock(status_code=200)

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post.side_effect = [cadence_resp, step_resp, step_resp]
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await _create_cadence_with_emails(
                "token", "Acme", [{"subject": "S1", "body": "B1"}, {"subject": "S2", "body": "B2"}],
            )

        assert result == 42
        assert mock_client.post.call_count == 3

    @pytest.mark.asyncio
    async def test_returns_none_on_create_failure(self):
        from services.salesloft import _create_cadence_with_emails

        cadence_resp = MagicMock(status_code=500, text="error")

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = cadence_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await _create_cadence_with_emails("token", "Acme", [{"subject": "S", "body": "B"}])

        assert result is None


class TestSalesLoftPushSequences:
    @pytest.mark.asyncio
    async def test_creates_cadences(self):
        from services.salesloft import push_sequences_to_salesloft

        accounts = [{"id": 1, "company_name": "Acme"}, {"id": 2, "company_name": "Beta"}]
        drafts = {1: [{"subject": "Hi", "body": "Hello"}], 2: [{"subject": "Hey", "body": "World"}]}

        with patch("services.salesloft.get_valid_token", new_callable=AsyncMock, return_value="token"), \
             patch("services.salesloft._create_cadence_with_emails", new_callable=AsyncMock, return_value=42):

            result = await push_sequences_to_salesloft(1, accounts, drafts)

        assert result["cadences_created"] == 2
        assert result["skipped"] == 0
        assert len(result["created_ids"]) == 2

    @pytest.mark.asyncio
    async def test_skips_without_drafts(self):
        from services.salesloft import push_sequences_to_salesloft

        accounts = [{"id": 1, "company_name": "Acme"}, {"id": 2, "company_name": "Beta"}]
        drafts = {1: [{"subject": "Hi", "body": "Hello"}]}

        with patch("services.salesloft.get_valid_token", new_callable=AsyncMock, return_value="token"), \
             patch("services.salesloft._create_cadence_with_emails", new_callable=AsyncMock, return_value=42):

            result = await push_sequences_to_salesloft(1, accounts, drafts)

        assert result["cadences_created"] == 1
        assert result["skipped"] == 1

    @pytest.mark.asyncio
    async def test_counts_errors(self):
        from services.salesloft import push_sequences_to_salesloft

        accounts = [{"id": 1, "company_name": "Acme"}]
        drafts = {1: [{"subject": "Hi", "body": "Hello"}]}

        with patch("services.salesloft.get_valid_token", new_callable=AsyncMock, return_value="token"), \
             patch("services.salesloft._create_cadence_with_emails", new_callable=AsyncMock, return_value=None):

            result = await push_sequences_to_salesloft(1, accounts, drafts)

        assert result["errors"] == 1
        assert result["cadences_created"] == 0
