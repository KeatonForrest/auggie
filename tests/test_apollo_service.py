"""
test_apollo_service.py - Tests for Apollo.io integration service.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

import httpx


# =============================================================================
# Integration functions
# =============================================================================

class TestApolloValidateApiKey:
    @pytest.mark.asyncio
    async def test_valid_key(self):
        from services.apollo import validate_integration_api_key

        mock_resp = MagicMock(status_code=200)
        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            assert await validate_integration_api_key("good-key") is True

    @pytest.mark.asyncio
    async def test_invalid_key(self):
        from services.apollo import validate_integration_api_key

        mock_resp = MagicMock(status_code=401)
        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            assert await validate_integration_api_key("bad-key") is False


class TestApolloGetIntegrationApiKey:
    @pytest.mark.asyncio
    async def test_returns_key(self):
        from services.apollo import _get_integration_api_key

        with patch("services.apollo.get_integration", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {"access_token": "my-key"}
            key = await _get_integration_api_key(1)

        assert key == "my-key"

    @pytest.mark.asyncio
    async def test_raises_when_not_connected(self):
        from services.apollo import _get_integration_api_key

        with patch("services.apollo.get_integration", new_callable=AsyncMock, return_value=None):
            with pytest.raises(RuntimeError, match="Apollo not connected"):
                await _get_integration_api_key(1)


class TestApolloListSavedLists:
    @pytest.mark.asyncio
    async def test_returns_labels(self):
        from services.apollo import list_saved_lists

        mock_resp = MagicMock()
        mock_resp.json.return_value = [{"id": "l1", "name": "My List"}]
        mock_resp.raise_for_status = MagicMock()

        with patch("services.apollo._get_integration_api_key", new_callable=AsyncMock, return_value="key"), \
             patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            labels = await list_saved_lists(1)

        assert len(labels) == 1
        assert labels[0]["name"] == "My List"


class TestApolloFetchListCompanies:
    @pytest.mark.asyncio
    async def test_returns_companies(self):
        from services.apollo import fetch_list_companies

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"organizations": [{"name": "Acme"}]}
        mock_resp.raise_for_status = MagicMock()

        with patch("services.apollo._get_integration_api_key", new_callable=AsyncMock, return_value="key"), \
             patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            data = await fetch_list_companies(1, "list-1")

        assert data["organizations"][0]["name"] == "Acme"


class TestApolloPushSequences:
    @pytest.mark.asyncio
    async def test_creates_sequences(self):
        from services.apollo import push_sequences_to_apollo

        accounts = [
            {"id": 1, "company_name": "Acme"},
            {"id": 2, "company_name": "Beta"},
        ]
        drafts = {
            1: [{"subject": "Hi", "body": "Hello"}],
            2: [{"subject": "Hey", "body": "World"}],
        }

        with patch("services.apollo._get_integration_api_key", new_callable=AsyncMock, return_value="key"), \
             patch("services.apollo._create_apollo_sequence_with_emails", new_callable=AsyncMock, return_value="camp-1"), \
             patch("database.get_user_by_id", new_callable=AsyncMock, return_value={"target_personas": ""}):

            result = await push_sequences_to_apollo(1, accounts, drafts)

        assert result["sequences_created"] == 2
        assert result["skipped"] == 0
        assert result["errors"] == 0

    @pytest.mark.asyncio
    async def test_skips_accounts_without_drafts(self):
        from services.apollo import push_sequences_to_apollo

        accounts = [{"id": 1, "company_name": "Acme"}, {"id": 2, "company_name": "Beta"}]
        drafts = {1: [{"subject": "Hi", "body": "Hello"}]}

        with patch("services.apollo._get_integration_api_key", new_callable=AsyncMock, return_value="key"), \
             patch("services.apollo._create_apollo_sequence_with_emails", new_callable=AsyncMock, return_value="camp-1"), \
             patch("database.get_user_by_id", new_callable=AsyncMock, return_value={"target_personas": ""}):

            result = await push_sequences_to_apollo(1, accounts, drafts)

        assert result["sequences_created"] == 1
        assert result["skipped"] == 1

    @pytest.mark.asyncio
    async def test_counts_errors(self):
        from services.apollo import push_sequences_to_apollo

        accounts = [{"id": 1, "company_name": "Acme"}]
        drafts = {1: [{"subject": "Hi", "body": "Hello"}]}

        with patch("services.apollo._get_integration_api_key", new_callable=AsyncMock, return_value="key"), \
             patch("services.apollo._create_apollo_sequence_with_emails", new_callable=AsyncMock, return_value=None), \
             patch("database.get_user_by_id", new_callable=AsyncMock, return_value={"target_personas": ""}):

            result = await push_sequences_to_apollo(1, accounts, drafts)

        assert result["errors"] == 1
        assert result["sequences_created"] == 0


class TestApolloCreateSequenceWithEmails:
    @pytest.mark.asyncio
    async def test_creates_campaign_and_steps(self):
        from services.apollo import _create_apollo_sequence_with_emails

        seq_resp = MagicMock(status_code=200)
        seq_resp.json.return_value = {"emailer_campaign": {"id": "camp-1"}}
        step_resp = MagicMock(status_code=200)

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post.side_effect = [seq_resp, step_resp, step_resp]
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await _create_apollo_sequence_with_emails(
                "key", "Acme", [{"subject": "S1", "body": "B1"}, {"subject": "S2", "body": "B2"}],
            )

        assert result == "camp-1"
        assert mock_client.post.call_count == 3

    @pytest.mark.asyncio
    async def test_returns_none_on_create_failure(self):
        from services.apollo import _create_apollo_sequence_with_emails

        seq_resp = MagicMock(status_code=500, text="error")

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = seq_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await _create_apollo_sequence_with_emails("key", "Acme", [{"subject": "S", "body": "B"}])

        assert result is None


class TestApolloGetFirmographicsForUser:
    @pytest.mark.asyncio
    async def test_returns_none_when_not_connected(self):
        from services.apollo import get_firmographics_for_user

        with patch("services.apollo.get_integration", new_callable=AsyncMock, return_value=None):
            result = await get_firmographics_for_user(1, "https://acme.com")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_formatted_data(self):
        from services.apollo import get_firmographics_for_user

        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {
            "organizations": [{"name": "Acme", "industry": "SaaS", "estimated_num_employees": 500}]
        }

        with patch("services.apollo.get_integration", new_callable=AsyncMock, return_value={"access_token": "key"}), \
             patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await get_firmographics_for_user(1, "https://acme.com")

        assert "Acme" in result
        assert "SaaS" in result
        assert "500" in result

    @pytest.mark.asyncio
    async def test_returns_none_on_api_error(self):
        from services.apollo import get_firmographics_for_user

        mock_resp = MagicMock(status_code=500)

        with patch("services.apollo.get_integration", new_callable=AsyncMock, return_value={"access_token": "key"}), \
             patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await get_firmographics_for_user(1, "https://acme.com")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_only_name(self):
        from services.apollo import get_firmographics_for_user

        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"organizations": [{"name": "Acme"}]}

        with patch("services.apollo.get_integration", new_callable=AsyncMock, return_value={"access_token": "key"}), \
             patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await get_firmographics_for_user(1, "https://acme.com")

        assert result is None


class TestApolloPlainToHtml:
    def test_escapes_and_converts(self):
        from services.apollo import _plain_to_html
        assert "&lt;" in _plain_to_html("<b>")
        assert "<br>" in _plain_to_html("a\nb")
        assert "</p><p>" in _plain_to_html("a\n\nb")
