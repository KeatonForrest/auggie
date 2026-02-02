"""Tests for services/instantly.py"""

import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock, AsyncMock

from services import instantly


class TestValidateApiKey:
    """Tests for validate_api_key function."""

    @pytest.mark.asyncio
    async def test_validate_api_key_success(self):
        """Test successful API key validation (200 response)."""
        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await instantly.validate_api_key("test_api_key")

        assert result is True
        mock_client.get.assert_called_once_with(
            "https://api.instantly.ai/api/v2/campaigns",
            headers={"Authorization": "Bearer test_api_key"},
            params={"limit": 1},
        )

    @pytest.mark.asyncio
    async def test_validate_api_key_failure(self):
        """Test failed API key validation (401 response)."""
        mock_response = MagicMock()
        mock_response.status_code = 401

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await instantly.validate_api_key("invalid_key")

        assert result is False

    @pytest.mark.asyncio
    async def test_validate_api_key_server_error(self):
        """Test API key validation with server error (500 response)."""
        mock_response = MagicMock()
        mock_response.status_code = 500

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await instantly.validate_api_key("test_api_key")

        assert result is False


class TestGetApiKey:
    """Tests for _get_api_key function."""

    @pytest.mark.asyncio
    async def test_get_api_key_success(self):
        """Test successfully retrieving API key from integration."""
        mock_integration = {
            "user_id": 1,
            "integration_type": "instantly",
            "access_token": "test_token_123",
        }

        with patch("services.instantly.get_integration", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_integration
            result = await instantly._get_api_key(1)

        assert result == "test_token_123"
        mock_get.assert_called_once_with(1, "instantly")

    @pytest.mark.asyncio
    async def test_get_api_key_not_connected(self):
        """Test that RuntimeError is raised when integration doesn't exist."""
        with patch("services.instantly.get_integration", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = None

            with pytest.raises(RuntimeError, match="Instantly not connected"):
                await instantly._get_api_key(1)


class TestListCampaigns:
    """Tests for list_campaigns function."""

    @pytest.mark.asyncio
    async def test_list_campaigns_success(self):
        """Test successfully listing campaigns."""
        campaigns_data = [
            {"id": "campaign_1", "name": "Campaign One", "other_field": "ignored"},
            {"id": "campaign_2", "name": "Campaign Two"},
            {"id": "campaign_3", "name": "Campaign Three"},
        ]

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = campaigns_data
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch("services.instantly._get_api_key", new_callable=AsyncMock) as mock_get_key:
            mock_get_key.return_value = "test_api_key"
            with patch("httpx.AsyncClient", return_value=mock_client):
                result = await instantly.list_campaigns(1)

        assert result == campaigns_data
        mock_client.get.assert_called_once_with(
            "https://api.instantly.ai/api/v2/campaigns",
            headers={"Authorization": "Bearer test_api_key"},
        )
        mock_response.raise_for_status.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_campaigns_empty_list(self):
        """Test listing campaigns when none exist."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = []
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch("services.instantly._get_api_key", new_callable=AsyncMock) as mock_get_key:
            mock_get_key.return_value = "test_api_key"
            with patch("httpx.AsyncClient", return_value=mock_client):
                result = await instantly.list_campaigns(1)

        assert result == []

    @pytest.mark.asyncio
    async def test_list_campaigns_http_error(self):
        """Test list_campaigns raises HTTPError on bad response."""
        from httpx import HTTPStatusError

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.raise_for_status.side_effect = HTTPStatusError(
            "Unauthorized", request=MagicMock(), response=mock_response
        )

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch("services.instantly._get_api_key", new_callable=AsyncMock) as mock_get_key:
            mock_get_key.return_value = "test_api_key"
            with patch("httpx.AsyncClient", return_value=mock_client):
                with pytest.raises(HTTPStatusError):
                    await instantly.list_campaigns(1)


class TestAddLeadsToCampaign:
    """Tests for add_leads_to_campaign function."""

    @pytest.mark.asyncio
    async def test_add_leads_to_campaign_success(self):
        """Test successfully adding leads to a campaign."""
        leads = [
            {
                "email": "john@example.com",
                "first_name": "John",
                "last_name": "Doe",
                "company_name": "Example Corp",
                "custom_variables": {"title": "CEO", "company_url": "https://example.com"},
            },
            {
                "email": "jane@example.com",
                "first_name": "Jane",
                "last_name": "Smith",
                "company_name": "Another Corp",
            },
        ]

        api_response = {"success": True, "added": 2}

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = api_response
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch("services.instantly._get_api_key", new_callable=AsyncMock) as mock_get_key:
            mock_get_key.return_value = "test_api_key"
            with patch("httpx.AsyncClient", return_value=mock_client):
                result = await instantly.add_leads_to_campaign(1, "campaign_123", leads)

        assert result == api_response
        mock_client.post.assert_called_once_with(
            "https://api.instantly.ai/api/v2/leads",
            headers={"Authorization": "Bearer test_api_key"},
            json={
                "campaign_id": "campaign_123",
                "skip_if_in_workspace": True,
                "leads": leads,
            },
        )
        mock_response.raise_for_status.assert_called_once()

    @pytest.mark.asyncio
    async def test_add_leads_to_campaign_empty_list(self):
        """Test adding empty leads list."""
        api_response = {"success": True, "added": 0}

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = api_response
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch("services.instantly._get_api_key", new_callable=AsyncMock) as mock_get_key:
            mock_get_key.return_value = "test_api_key"
            with patch("httpx.AsyncClient", return_value=mock_client):
                result = await instantly.add_leads_to_campaign(1, "campaign_123", [])

        assert result == api_response
        call_args = mock_client.post.call_args
        assert call_args[1]["json"]["leads"] == []

    @pytest.mark.asyncio
    async def test_add_leads_to_campaign_http_error(self):
        """Test add_leads_to_campaign raises HTTPError on bad response."""
        from httpx import HTTPStatusError

        leads = [{"email": "test@example.com", "first_name": "Test"}]

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = HTTPStatusError(
            "Server Error", request=MagicMock(), response=mock_response
        )

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch("services.instantly._get_api_key", new_callable=AsyncMock) as mock_get_key:
            mock_get_key.return_value = "test_api_key"
            with patch("httpx.AsyncClient", return_value=mock_client):
                with pytest.raises(HTTPStatusError):
                    await instantly.add_leads_to_campaign(1, "campaign_123", leads)


class TestPushAccountsToInstantly:
    """Tests for push_accounts_to_instantly function."""

    @pytest.mark.asyncio
    async def test_push_accounts_success_with_contacts(self):
        """Test successfully pushing accounts with contacts to Instantly."""
        accounts = [
            {
                "id": 1,
                "company_name": "Acme Corp",
                "company_url": "https://acme.com",
                "pain_score": 8,
                "fit_score": 7,
                "composite_score": 7.5,
            },
            {
                "id": 2,
                "company_name": "TechCo",
                "company_url": "https://techco.com",
                "pain_score": 6,
                "fit_score": 9,
                "composite_score": 7.5,
            },
        ]

        contacts_by_account = {
            1: [
                {
                    "email": "john@acme.com",
                    "first_name": "John",
                    "last_name": "Doe",
                    "title": "CEO",
                },
                {
                    "email": "jane@acme.com",
                    "first_name": "Jane",
                    "last_name": "Smith",
                    "title": "CTO",
                },
            ],
            2: [
                {
                    "email": "bob@techco.com",
                    "first_name": "Bob",
                    "last_name": "Johnson",
                    "title": "VP Sales",
                },
            ],
        }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"success": True}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch("services.instantly._get_api_key", new_callable=AsyncMock) as mock_get_key:
            mock_get_key.return_value = "test_api_key"
            with patch("httpx.AsyncClient", return_value=mock_client):
                with patch("services.instantly.update_list_account_pushed", new_callable=AsyncMock) as mock_update:
                    result = await instantly.push_accounts_to_instantly(
                        1, "campaign_123", accounts, contacts_by_account
                    )

        assert result["pushed"] == 3  # 3 total leads
        assert result["skipped"] == 0
        assert result["errors"] == 0

        # Verify leads were built correctly
        call_args = mock_client.post.call_args
        posted_leads = call_args[1]["json"]["leads"]
        assert len(posted_leads) == 3

        # Check first lead structure
        assert posted_leads[0]["email"] == "john@acme.com"
        assert posted_leads[0]["first_name"] == "John"
        assert posted_leads[0]["last_name"] == "Doe"
        assert posted_leads[0]["company_name"] == "Acme Corp"
        assert posted_leads[0]["custom_variables"]["company_url"] == "https://acme.com"
        assert posted_leads[0]["custom_variables"]["pain_score"] == "8"
        assert posted_leads[0]["custom_variables"]["fit_score"] == "7"
        assert posted_leads[0]["custom_variables"]["composite_score"] == "7.5"
        assert posted_leads[0]["custom_variables"]["title"] == "CEO"

        # Verify both accounts were marked as pushed
        assert mock_update.call_count == 2
        update_calls = [call[0] for call in mock_update.call_args_list]
        account_ids_updated = {call[0] for call in update_calls}
        assert account_ids_updated == {1, 2}

        # Check that update was called with correct parameters
        for call in mock_update.call_args_list:
            assert call[0][1] == "instantly"
            assert call[0][2]["campaign_id"] == "campaign_123"
            assert "pushed_at" in call[0][2]

    @pytest.mark.asyncio
    async def test_push_accounts_skips_accounts_without_contacts(self):
        """Test that accounts without contacts are skipped."""
        accounts = [
            {"id": 1, "company_name": "Acme Corp"},
            {"id": 2, "company_name": "TechCo"},
            {"id": 3, "company_name": "NoContacts Inc"},
        ]

        contacts_by_account = {
            1: [{"email": "john@acme.com", "first_name": "John", "last_name": "Doe"}],
            2: [],  # Empty contact list
            # Account 3 has no entry in contacts_by_account
        }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"success": True}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch("services.instantly._get_api_key", new_callable=AsyncMock) as mock_get_key:
            mock_get_key.return_value = "test_api_key"
            with patch("httpx.AsyncClient", return_value=mock_client):
                with patch("services.instantly.update_list_account_pushed", new_callable=AsyncMock) as mock_update:
                    result = await instantly.push_accounts_to_instantly(
                        1, "campaign_123", accounts, contacts_by_account
                    )

        assert result["pushed"] == 1  # Only 1 lead from account 1
        assert result["skipped"] == 2  # Accounts 2 and 3 skipped
        assert result["errors"] == 0

        # Only account 1 should be marked as pushed
        assert mock_update.call_count == 1
        mock_update.assert_called_once()
        assert mock_update.call_args[0][0] == 1

    @pytest.mark.asyncio
    async def test_push_accounts_skips_contacts_without_email(self):
        """Test that contacts without email addresses are skipped."""
        accounts = [
            {"id": 1, "company_name": "Acme Corp"},
        ]

        contacts_by_account = {
            1: [
                {"email": "john@acme.com", "first_name": "John", "last_name": "Doe"},
                {"email": "", "first_name": "Jane", "last_name": "Smith"},  # Empty email
                {"first_name": "Bob", "last_name": "Johnson"},  # No email field
                {"email": None, "first_name": "Alice", "last_name": "Brown"},  # None email
            ],
        }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"success": True}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch("services.instantly._get_api_key", new_callable=AsyncMock) as mock_get_key:
            mock_get_key.return_value = "test_api_key"
            with patch("httpx.AsyncClient", return_value=mock_client):
                with patch("services.instantly.update_list_account_pushed", new_callable=AsyncMock) as mock_update:
                    result = await instantly.push_accounts_to_instantly(
                        1, "campaign_123", accounts, contacts_by_account
                    )

        assert result["pushed"] == 1  # Only John with valid email
        assert result["errors"] == 0

        # Verify only one lead was posted
        call_args = mock_client.post.call_args
        posted_leads = call_args[1]["json"]["leads"]
        assert len(posted_leads) == 1
        assert posted_leads[0]["email"] == "john@acme.com"

    @pytest.mark.asyncio
    async def test_push_accounts_handles_missing_optional_fields(self):
        """Test that missing optional fields are handled with empty strings."""
        accounts = [
            {
                "id": 1,
                # Missing optional fields: company_name, company_url, scores
            },
        ]

        contacts_by_account = {
            1: [
                {
                    "email": "john@example.com",
                    # Missing optional fields: first_name, last_name, title
                },
            ],
        }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"success": True}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch("services.instantly._get_api_key", new_callable=AsyncMock) as mock_get_key:
            mock_get_key.return_value = "test_api_key"
            with patch("httpx.AsyncClient", return_value=mock_client):
                with patch("services.instantly.update_list_account_pushed", new_callable=AsyncMock) as mock_update:
                    result = await instantly.push_accounts_to_instantly(
                        1, "campaign_123", accounts, contacts_by_account
                    )

        assert result["pushed"] == 1
        assert result["errors"] == 0

        # Verify lead was built with empty strings for missing fields
        call_args = mock_client.post.call_args
        posted_leads = call_args[1]["json"]["leads"]
        assert len(posted_leads) == 1
        lead = posted_leads[0]
        assert lead["email"] == "john@example.com"
        assert lead["first_name"] == ""
        assert lead["last_name"] == ""
        assert lead["company_name"] == ""
        assert lead["custom_variables"]["company_url"] == ""
        assert lead["custom_variables"]["pain_score"] == ""
        assert lead["custom_variables"]["fit_score"] == ""
        assert lead["custom_variables"]["composite_score"] == ""
        assert lead["custom_variables"]["title"] == ""

    @pytest.mark.asyncio
    async def test_push_accounts_handles_api_error(self):
        """Test that API errors are caught and returned in error count."""
        accounts = [
            {"id": 1, "company_name": "Acme Corp"},
        ]

        contacts_by_account = {
            1: [
                {"email": "john@acme.com", "first_name": "John", "last_name": "Doe"},
            ],
        }

        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = Exception("API connection failed")

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch("services.instantly._get_api_key", new_callable=AsyncMock) as mock_get_key:
            mock_get_key.return_value = "test_api_key"
            with patch("httpx.AsyncClient", return_value=mock_client):
                with patch("services.instantly.update_list_account_pushed", new_callable=AsyncMock) as mock_update:
                    result = await instantly.push_accounts_to_instantly(
                        1, "campaign_123", accounts, contacts_by_account
                    )

        assert result["pushed"] == 0
        assert result["skipped"] == 0
        assert result["errors"] == 1  # 1 lead failed
        assert "error" in result
        assert "API connection failed" in result["error"]

        # No accounts should be marked as pushed on error
        mock_update.assert_not_called()

    @pytest.mark.asyncio
    async def test_push_accounts_handles_get_api_key_error(self):
        """Test that errors during API key retrieval are caught."""
        accounts = [
            {"id": 1, "company_name": "Acme Corp"},
        ]

        contacts_by_account = {
            1: [
                {"email": "john@acme.com", "first_name": "John", "last_name": "Doe"},
            ],
        }

        with patch("services.instantly._get_api_key", new_callable=AsyncMock) as mock_get_key:
            mock_get_key.side_effect = RuntimeError("Instantly not connected")
            with patch("services.instantly.update_list_account_pushed", new_callable=AsyncMock) as mock_update:
                result = await instantly.push_accounts_to_instantly(
                    1, "campaign_123", accounts, contacts_by_account
                )

        assert result["pushed"] == 0
        assert result["skipped"] == 0
        assert result["errors"] == 1
        assert "error" in result
        assert "Instantly not connected" in result["error"]

        # No accounts should be marked as pushed on error
        mock_update.assert_not_called()

    @pytest.mark.asyncio
    async def test_push_accounts_no_leads_returns_all_skipped(self):
        """Test that when no valid leads are created, all accounts are marked as skipped."""
        accounts = [
            {"id": 1, "company_name": "Acme Corp"},
            {"id": 2, "company_name": "TechCo"},
        ]

        contacts_by_account = {}  # No contacts at all

        with patch("services.instantly._get_api_key", new_callable=AsyncMock):
            result = await instantly.push_accounts_to_instantly(
                1, "campaign_123", accounts, contacts_by_account
            )

        assert result["pushed"] == 0
        assert result["skipped"] == 2
        assert result["errors"] == 0

    @pytest.mark.asyncio
    async def test_push_accounts_multiple_contacts_per_account(self):
        """Test pushing multiple contacts from the same account."""
        accounts = [
            {
                "id": 1,
                "company_name": "Acme Corp",
                "company_url": "https://acme.com",
                "pain_score": 8,
                "fit_score": 7,
                "composite_score": 7.5,
            },
        ]

        contacts_by_account = {
            1: [
                {"email": "john@acme.com", "first_name": "John", "last_name": "Doe", "title": "CEO"},
                {"email": "jane@acme.com", "first_name": "Jane", "last_name": "Smith", "title": "CTO"},
                {"email": "bob@acme.com", "first_name": "Bob", "last_name": "Johnson", "title": "CFO"},
            ],
        }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"success": True}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch("services.instantly._get_api_key", new_callable=AsyncMock) as mock_get_key:
            mock_get_key.return_value = "test_api_key"
            with patch("httpx.AsyncClient", return_value=mock_client):
                with patch("services.instantly.update_list_account_pushed", new_callable=AsyncMock) as mock_update:
                    result = await instantly.push_accounts_to_instantly(
                        1, "campaign_123", accounts, contacts_by_account
                    )

        assert result["pushed"] == 3  # All 3 contacts
        assert result["skipped"] == 0
        assert result["errors"] == 0

        # Verify all 3 leads were posted
        call_args = mock_client.post.call_args
        posted_leads = call_args[1]["json"]["leads"]
        assert len(posted_leads) == 3

        # Account should only be updated once even with multiple contacts
        assert mock_update.call_count == 1
        assert mock_update.call_args[0][0] == 1

    @pytest.mark.asyncio
    async def test_push_accounts_error_truncates_long_error_message(self):
        """Test that error messages longer than 500 chars are truncated."""
        accounts = [
            {"id": 1, "company_name": "Acme Corp"},
        ]

        contacts_by_account = {
            1: [{"email": "john@acme.com", "first_name": "John", "last_name": "Doe"}],
        }

        # Create a very long error message
        long_error = "x" * 1000

        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = Exception(long_error)

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch("services.instantly._get_api_key", new_callable=AsyncMock) as mock_get_key:
            mock_get_key.return_value = "test_api_key"
            with patch("httpx.AsyncClient", return_value=mock_client):
                with patch("services.instantly.update_list_account_pushed", new_callable=AsyncMock):
                    result = await instantly.push_accounts_to_instantly(
                        1, "campaign_123", accounts, contacts_by_account
                    )

        assert result["errors"] == 1
        assert "error" in result
        # Error message should be truncated to 500 chars
        assert len(result["error"]) == 500
        assert result["error"] == "x" * 500
