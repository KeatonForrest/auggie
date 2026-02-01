"""Tests for services/smartlead.py"""

import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock, AsyncMock

from services import smartlead


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
            result = await smartlead.validate_api_key("test_api_key")

        assert result is True
        mock_client.get.assert_called_once_with(
            "https://server.smartlead.ai/api/v1/campaigns",
            params={"api_key": "test_api_key"},
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
            result = await smartlead.validate_api_key("invalid_key")

        assert result is False


class TestGetApiKey:
    """Tests for _get_api_key function."""

    @pytest.mark.asyncio
    async def test_get_api_key_success(self):
        """Test successfully retrieving API key from integration."""
        mock_integration = {
            "user_id": 1,
            "integration_type": "smartlead",
            "access_token": "test_token_123",
        }

        with patch("services.smartlead.get_integration", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_integration
            result = await smartlead._get_api_key(1)

        assert result == "test_token_123"
        mock_get.assert_called_once_with(1, "smartlead")

    @pytest.mark.asyncio
    async def test_get_api_key_not_connected(self):
        """Test that RuntimeError is raised when integration doesn't exist."""
        with patch("services.smartlead.get_integration", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = None

            with pytest.raises(RuntimeError, match="Smartlead not connected"):
                await smartlead._get_api_key(1)


class TestListCampaigns:
    """Tests for list_campaigns function."""

    @pytest.mark.asyncio
    async def test_list_campaigns_returns_formatted_list(self):
        """Test that campaigns are properly formatted with id and name."""
        campaigns_data = [
            {"id": "campaign_1", "name": "Campaign One", "other_field": "ignored"},
            {"id": "campaign_2", "name": "Campaign Two"},
            {"id": "campaign_3", "name": ""},  # Empty name should be included
        ]

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = campaigns_data

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch("services.smartlead._get_api_key", new_callable=AsyncMock) as mock_get_key:
            mock_get_key.return_value = "test_api_key"
            with patch("httpx.AsyncClient", return_value=mock_client):
                result = await smartlead.list_campaigns(1)

        assert len(result) == 3
        assert result[0] == {"id": "campaign_1", "name": "Campaign One"}
        assert result[1] == {"id": "campaign_2", "name": "Campaign Two"}
        assert result[2] == {"id": "campaign_3", "name": ""}

    @pytest.mark.asyncio
    async def test_list_campaigns_filters_non_dicts(self):
        """Test that non-dict items in campaigns list are filtered out."""
        campaigns_data = [
            {"id": "campaign_1", "name": "Campaign One"},
            "invalid_string_item",
            None,
            {"id": "campaign_2", "name": "Campaign Two"},
            123,  # Number
            [],  # List
        ]

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = campaigns_data

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch("services.smartlead._get_api_key", new_callable=AsyncMock) as mock_get_key:
            mock_get_key.return_value = "test_api_key"
            with patch("httpx.AsyncClient", return_value=mock_client):
                result = await smartlead.list_campaigns(1)

        # Should only include the two valid dict items
        assert len(result) == 2
        assert result[0] == {"id": "campaign_1", "name": "Campaign One"}
        assert result[1] == {"id": "campaign_2", "name": "Campaign Two"}


class TestAddLeadsToCampaign:
    """Tests for add_leads_to_campaign function."""

    @pytest.mark.asyncio
    async def test_add_leads_to_campaign_posts_correctly(self):
        """Test that leads are posted with correct structure."""
        leads = [
            {
                "email": "john@example.com",
                "first_name": "John",
                "last_name": "Doe",
                "company_name": "Example Corp",
                "custom_fields": {"title": "CEO"},
            },
            {
                "email": "jane@example.com",
                "first_name": "Jane",
                "last_name": "Smith",
                "company_name": "Another Corp",
            },
        ]

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"success": True}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch("services.smartlead._get_api_key", new_callable=AsyncMock) as mock_get_key:
            mock_get_key.return_value = "test_api_key"
            with patch("httpx.AsyncClient", return_value=mock_client):
                result = await smartlead.add_leads_to_campaign(1, "campaign_123", leads)

        assert result == {"success": True}
        mock_client.post.assert_called_once_with(
            "https://server.smartlead.ai/api/v1/campaigns/campaign_123/leads",
            params={"api_key": "test_api_key"},
            json={"lead_list": leads},
        )


class TestPushAccountsToSmartlead:
    """Tests for push_accounts_to_smartlead function."""

    @pytest.mark.asyncio
    async def test_push_accounts_success_with_contacts(self):
        """Test successfully pushing accounts with contacts to Smartlead."""
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

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch("services.smartlead._get_api_key", new_callable=AsyncMock) as mock_get_key:
            mock_get_key.return_value = "test_api_key"
            with patch("httpx.AsyncClient", return_value=mock_client):
                with patch("services.smartlead.update_list_account_pushed", new_callable=AsyncMock) as mock_update:
                    result = await smartlead.push_accounts_to_smartlead(
                        1, "campaign_123", accounts, contacts_by_account
                    )

        assert result["pushed"] == 3  # 3 total leads
        assert result["skipped"] == 0
        assert result["errors"] == 0

        # Verify leads were built correctly
        call_args = mock_client.post.call_args
        posted_leads = call_args[1]["json"]["lead_list"]
        assert len(posted_leads) == 3

        # Check first lead structure
        assert posted_leads[0]["email"] == "john@acme.com"
        assert posted_leads[0]["first_name"] == "John"
        assert posted_leads[0]["last_name"] == "Doe"
        assert posted_leads[0]["company_name"] == "Acme Corp"
        assert posted_leads[0]["custom_fields"]["company_url"] == "https://acme.com"
        assert posted_leads[0]["custom_fields"]["pain_score"] == "8"
        assert posted_leads[0]["custom_fields"]["fit_score"] == "7"
        assert posted_leads[0]["custom_fields"]["composite_score"] == "7.5"
        assert posted_leads[0]["custom_fields"]["title"] == "CEO"

        # Verify both accounts were marked as pushed
        assert mock_update.call_count == 2
        update_calls = [call[0] for call in mock_update.call_args_list]
        account_ids_updated = {call[0] for call in update_calls}
        assert account_ids_updated == {1, 2}

        # Check that update was called with correct parameters
        for call in mock_update.call_args_list:
            assert call[0][1] == "smartlead"
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

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch("services.smartlead._get_api_key", new_callable=AsyncMock) as mock_get_key:
            mock_get_key.return_value = "test_api_key"
            with patch("httpx.AsyncClient", return_value=mock_client):
                with patch("services.smartlead.update_list_account_pushed", new_callable=AsyncMock) as mock_update:
                    result = await smartlead.push_accounts_to_smartlead(
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

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch("services.smartlead._get_api_key", new_callable=AsyncMock) as mock_get_key:
            mock_get_key.return_value = "test_api_key"
            with patch("httpx.AsyncClient", return_value=mock_client):
                with patch("services.smartlead.update_list_account_pushed", new_callable=AsyncMock) as mock_update:
                    result = await smartlead.push_accounts_to_smartlead(
                        1, "campaign_123", accounts, contacts_by_account
                    )

        assert result["pushed"] == 1  # Only John with valid email
        assert result["errors"] == 0

        # Verify only one lead was posted
        call_args = mock_client.post.call_args
        posted_leads = call_args[1]["json"]["lead_list"]
        assert len(posted_leads) == 1
        assert posted_leads[0]["email"] == "john@acme.com"

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

        mock_client = AsyncMock()
        mock_client.post.side_effect = Exception("API connection failed")
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch("services.smartlead._get_api_key", new_callable=AsyncMock) as mock_get_key:
            mock_get_key.return_value = "test_api_key"
            with patch("httpx.AsyncClient", return_value=mock_client):
                with patch("services.smartlead.update_list_account_pushed", new_callable=AsyncMock) as mock_update:
                    result = await smartlead.push_accounts_to_smartlead(
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
    async def test_push_accounts_no_leads_returns_all_skipped(self):
        """Test that when no valid leads are created, all accounts are marked as skipped."""
        accounts = [
            {"id": 1, "company_name": "Acme Corp"},
            {"id": 2, "company_name": "TechCo"},
        ]

        contacts_by_account = {}  # No contacts at all

        with patch("services.smartlead._get_api_key", new_callable=AsyncMock):
            result = await smartlead.push_accounts_to_smartlead(
                1, "campaign_123", accounts, contacts_by_account
            )

        assert result["pushed"] == 0
        assert result["skipped"] == 2
        assert result["errors"] == 0
