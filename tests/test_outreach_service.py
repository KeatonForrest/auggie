"""
test_outreach_service.py - Tests for Outreach integration service.
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch, MagicMock


class TestOutreachAuthorizeUrl:
    def test_builds_correct_url(self):
        from services.outreach import get_authorize_url, OUTREACH_AUTH_URL, SCOPES

        with patch("services.outreach.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                outreach_client_id="or-client",
                app_url="https://app.example.com",
            )
            url = get_authorize_url("state-or")

        assert url.startswith(OUTREACH_AUTH_URL)
        assert "client_id=or-client" in url
        assert "state=state-or" in url
        assert "response_type=code" in url
        assert SCOPES.replace(" ", "%20") in url or SCOPES in url


class TestOutreachExchangeCode:
    @pytest.mark.asyncio
    async def test_exchanges_code(self):
        from services.outreach import exchange_code

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"access_token": "or-token", "refresh_token": "or-rt", "expires_in": 7200}
        mock_resp.raise_for_status = MagicMock()

        with patch("services.outreach.get_settings") as mock_settings, \
             patch("httpx.AsyncClient") as mock_cls:
            mock_settings.return_value = MagicMock(
                outreach_client_id="cid", outreach_client_secret="csecret",
                app_url="https://app.example.com",
            )
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await exchange_code("auth-code-or")

        assert result["access_token"] == "or-token"
        call_data = mock_client.post.call_args[1]["data"]
        assert call_data["code"] == "auth-code-or"
        assert call_data["grant_type"] == "authorization_code"


class TestOutreachTokenRefresh:
    @pytest.mark.asyncio
    async def test_returns_valid_token(self):
        from services.outreach import refresh_access_token

        future = datetime.now(timezone.utc) + timedelta(hours=2)
        with patch("services.outreach.get_integration", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {"access_token": "valid", "refresh_token": "rt", "token_expires_at": future}
            token = await refresh_access_token(1)

        assert token == "valid"

    @pytest.mark.asyncio
    async def test_refreshes_expired_token(self):
        from services.outreach import refresh_access_token

        past = datetime.now(timezone.utc) - timedelta(minutes=10)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"access_token": "new-token", "refresh_token": "new-rt", "expires_in": 7200}
        mock_resp.raise_for_status = MagicMock()

        with patch("services.outreach.get_integration", new_callable=AsyncMock) as mock_get, \
             patch("services.outreach.update_integration_tokens", new_callable=AsyncMock) as mock_update, \
             patch("services.outreach.get_settings") as mock_settings, \
             patch("httpx.AsyncClient") as mock_cls:
            mock_get.return_value = {"access_token": "expired", "refresh_token": "old-rt", "token_expires_at": past}
            mock_settings.return_value = MagicMock(
                outreach_client_id="cid", outreach_client_secret="csecret",
                app_url="https://app.example.com",
            )
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
        from services.outreach import refresh_access_token

        with patch("services.outreach.get_integration", new_callable=AsyncMock, return_value=None):
            with pytest.raises(RuntimeError, match="Outreach not connected"):
                await refresh_access_token(1)


class TestOutreachListSequences:
    @pytest.mark.asyncio
    async def test_returns_sequences(self):
        from services.outreach import list_sequences

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "data": [
                {"id": 1, "attributes": {"name": "Seq A"}},
                {"id": 2, "attributes": {"name": "Seq B"}},
            ]
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("services.outreach.get_valid_token", new_callable=AsyncMock, return_value="token"), \
             patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            seqs = await list_sequences(1)

        assert len(seqs) == 2
        assert seqs[0] == {"id": 1, "name": "Seq A"}

    @pytest.mark.asyncio
    async def test_returns_empty(self):
        from services.outreach import list_sequences

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": []}
        mock_resp.raise_for_status = MagicMock()

        with patch("services.outreach.get_valid_token", new_callable=AsyncMock, return_value="token"), \
             patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            seqs = await list_sequences(1)

        assert seqs == []


class TestOutreachCreateSequence:
    @pytest.mark.asyncio
    async def test_creates_sequence_with_steps(self):
        from services.outreach import _create_sequence_with_emails

        seq_resp = MagicMock(status_code=200)
        seq_resp.json.return_value = {"data": {"id": 99}}
        tpl_resp = MagicMock(status_code=200)
        tpl_resp.json.return_value = {"data": {"id": 10}}
        step_resp = MagicMock(status_code=200)
        step_resp.json.return_value = {"data": {"id": 20}}
        link_resp = MagicMock(status_code=200)

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            # seq create, then for each email: template, step, link
            mock_client.post.side_effect = [seq_resp, tpl_resp, step_resp, link_resp]
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await _create_sequence_with_emails(
                "token", "Acme", [{"subject": "S1", "body": "B1"}],
            )

        assert result == 99
        assert mock_client.post.call_count == 4  # seq + template + step + link

    @pytest.mark.asyncio
    async def test_returns_none_on_create_failure(self):
        from services.outreach import _create_sequence_with_emails

        seq_resp = MagicMock(status_code=500, text="error")

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = seq_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await _create_sequence_with_emails("token", "Acme", [{"subject": "S", "body": "B"}])

        assert result is None


class TestOutreachPushSequences:
    @pytest.mark.asyncio
    async def test_creates_sequences(self):
        from services.outreach import push_sequences_to_outreach

        accounts = [{"id": 1, "company_name": "Acme"}, {"id": 2, "company_name": "Beta"}]
        drafts = {1: [{"subject": "Hi", "body": "Hello"}], 2: [{"subject": "Hey", "body": "World"}]}

        with patch("services.outreach.get_valid_token", new_callable=AsyncMock, return_value="token"), \
             patch("services.outreach._create_sequence_with_emails", new_callable=AsyncMock, return_value=99):

            result = await push_sequences_to_outreach(1, accounts, drafts)

        assert result["sequences_created"] == 2
        assert result["skipped"] == 0
        assert len(result["created_ids"]) == 2

    @pytest.mark.asyncio
    async def test_skips_without_drafts(self):
        from services.outreach import push_sequences_to_outreach

        accounts = [{"id": 1, "company_name": "Acme"}, {"id": 2, "company_name": "Beta"}]
        drafts = {1: [{"subject": "Hi", "body": "Hello"}]}

        with patch("services.outreach.get_valid_token", new_callable=AsyncMock, return_value="token"), \
             patch("services.outreach._create_sequence_with_emails", new_callable=AsyncMock, return_value=99):

            result = await push_sequences_to_outreach(1, accounts, drafts)

        assert result["sequences_created"] == 1
        assert result["skipped"] == 1

    @pytest.mark.asyncio
    async def test_counts_errors(self):
        from services.outreach import push_sequences_to_outreach

        accounts = [{"id": 1, "company_name": "Acme"}]
        drafts = {1: [{"subject": "Hi", "body": "Hello"}]}

        with patch("services.outreach.get_valid_token", new_callable=AsyncMock, return_value="token"), \
             patch("services.outreach._create_sequence_with_emails", new_callable=AsyncMock, return_value=None):

            result = await push_sequences_to_outreach(1, accounts, drafts)

        assert result["errors"] == 1
        assert result["sequences_created"] == 0


class TestOutreachPlainToHtml:
    def test_escapes_and_converts(self):
        from services.outreach import _plain_to_html
        assert "&lt;" in _plain_to_html("<b>")
        assert "<br>" in _plain_to_html("a\nb")
        assert "</p><p>" in _plain_to_html("a\n\nb")
