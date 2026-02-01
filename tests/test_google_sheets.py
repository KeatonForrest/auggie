import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime, timedelta, timezone
from services.google_sheets import (
    get_authorize_url,
    exchange_code,
    refresh_access_token,
    extract_spreadsheet_id,
    create_and_write_sheet,
    fetch_sheet_rows,
    GOOGLE_AUTH_URL,
    GOOGLE_TOKEN_URL,
    SHEETS_API_BASE,
    SCOPES,
)


class TestGetAuthorizeUrl:
    """Test get_authorize_url function."""

    @patch("services.google_sheets.get_settings")
    def test_builds_correct_url(self, mock_get_settings):
        """Test that the authorization URL is built correctly."""
        mock_settings = MagicMock()
        mock_settings.google_client_id = "test_client_id"
        mock_settings.app_url = "https://example.com"
        mock_get_settings.return_value = mock_settings

        state = "test_state_123"
        url = get_authorize_url(state)

        assert GOOGLE_AUTH_URL in url
        assert "client_id=test_client_id" in url
        assert f"state={state}" in url
        assert "scope=" in url
        assert "access_type=offline" in url
        assert "prompt=consent" in url
        assert "redirect_uri=" in url
        from urllib.parse import quote
        assert quote(SCOPES, safe='') in url

    @patch("services.google_sheets.get_settings")
    def test_includes_all_required_params(self, mock_get_settings):
        """Test that all required OAuth parameters are included."""
        mock_settings = MagicMock()
        mock_settings.google_client_id = "client_123"
        mock_settings.app_url = "https://app.example.com"
        mock_get_settings.return_value = mock_settings

        url = get_authorize_url("state_abc")

        assert "response_type=code" in url
        assert "access_type=offline" in url
        assert "prompt=consent" in url


class TestExchangeCode:
    """Test exchange_code function."""

    @pytest.mark.asyncio
    @patch("services.google_sheets.get_settings")
    async def test_posts_correctly_and_returns_token_data(self, mock_get_settings):
        """Test that exchange_code posts to Google and returns token data."""
        mock_settings = MagicMock()
        mock_settings.google_client_id = "client_id"
        mock_settings.google_client_secret = "client_secret"
        mock_settings.app_url = "https://example.com"
        mock_get_settings.return_value = mock_settings

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "access_123",
            "refresh_token": "refresh_456",
            "expires_in": 3600,
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        mock_cls = MagicMock()
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", mock_cls):
            result = await exchange_code("auth_code_123")

        assert result["access_token"] == "access_123"
        assert result["refresh_token"] == "refresh_456"
        assert result["expires_in"] == 3600

        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert call_args[0][0] == GOOGLE_TOKEN_URL
        assert call_args[1]["data"]["code"] == "auth_code_123"
        assert call_args[1]["data"]["grant_type"] == "authorization_code"


class TestRefreshAccessToken:
    """Test refresh_access_token function."""

    @pytest.mark.asyncio
    @patch("services.google_sheets.get_integration")
    async def test_valid_token_returned_without_refresh(self, mock_get_integration):
        """Test that a valid token is returned without refreshing."""
        future_time = datetime.now(timezone.utc) + timedelta(hours=1)
        mock_integration = {
            "access_token": "valid_token",
            "token_expires_at": future_time,
        }
        mock_get_integration.return_value = mock_integration

        token = await refresh_access_token(1)

        assert token == "valid_token"
        mock_get_integration.assert_called_once_with(1, "google_sheets")

    @pytest.mark.asyncio
    @patch("services.google_sheets.update_integration_tokens")
    @patch("services.google_sheets.get_settings")
    @patch("services.google_sheets.get_integration")
    async def test_expired_token_refreshed(
        self, mock_get_integration, mock_get_settings, mock_update_tokens
    ):
        """Test that an expired token triggers a refresh."""
        past_time = datetime.now(timezone.utc) - timedelta(hours=1)
        mock_integration = {
            "access_token": "old_token",
            "refresh_token": "refresh_token_123",
            "token_expires_at": past_time,
        }
        mock_get_integration.return_value = mock_integration

        mock_settings = MagicMock()
        mock_settings.google_client_id = "client_id"
        mock_settings.google_client_secret = "client_secret"
        mock_get_settings.return_value = mock_settings

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "new_token",
            "expires_in": 3600,
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        mock_cls = MagicMock()
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", mock_cls):
            token = await refresh_access_token(1)

        assert token == "new_token"
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert call_args[0][0] == GOOGLE_TOKEN_URL
        assert call_args[1]["data"]["refresh_token"] == "refresh_token_123"
        assert call_args[1]["data"]["grant_type"] == "refresh_token"

        mock_update_tokens.assert_called_once()
        update_args = mock_update_tokens.call_args
        assert update_args[0][0] == 1
        assert update_args[0][1] == "google_sheets"
        assert update_args[1]["access_token"] == "new_token"

    @pytest.mark.asyncio
    @patch("services.google_sheets.get_integration")
    async def test_not_connected_raises_runtime_error(self, mock_get_integration):
        """Test that RuntimeError is raised when integration doesn't exist."""
        mock_get_integration.return_value = None

        with pytest.raises(RuntimeError):
            await refresh_access_token(1)

        mock_get_integration.assert_called_once_with(1, "google_sheets")


class TestExtractSpreadsheetId:
    """Test extract_spreadsheet_id function."""

    def test_valid_url_extracts_id(self):
        """Test that a valid spreadsheet URL extracts the ID."""
        url = "https://docs.google.com/spreadsheets/d/1A2B3C4D5E6F7G8H9I0J/edit#gid=0"
        result = extract_spreadsheet_id(url)
        assert result == "1A2B3C4D5E6F7G8H9I0J"

    def test_valid_url_without_edit_suffix(self):
        """Test extraction from URL without /edit suffix."""
        url = "https://docs.google.com/spreadsheets/d/abc123xyz"
        result = extract_spreadsheet_id(url)
        assert result == "abc123xyz"

    def test_invalid_url_returns_none(self):
        """Test that an invalid URL returns None."""
        url = "https://example.com/not-a-spreadsheet"
        result = extract_spreadsheet_id(url)
        assert result is None

    def test_malformed_url_returns_none(self):
        """Test that a malformed spreadsheet URL returns None."""
        url = "https://docs.google.com/documents/d/123/edit"
        result = extract_spreadsheet_id(url)
        assert result is None


class TestCreateAndWriteSheet:
    """Test create_and_write_sheet function."""

    @pytest.mark.asyncio
    @patch("services.google_sheets.refresh_access_token")
    async def test_creates_and_writes_returns_url(self, mock_refresh_token):
        """Test that a spreadsheet is created, data is written, and URL is returned."""
        mock_refresh_token.return_value = "access_token_123"

        mock_create_response = MagicMock()
        mock_create_response.json.return_value = {
            "spreadsheetId": "new_sheet_id_123",
            "spreadsheetUrl": "https://docs.google.com/spreadsheets/d/new_sheet_id_123",
        }

        mock_update_response = MagicMock()
        mock_update_response.json.return_value = {
            "updatedCells": 10,
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_create_response)
        mock_client.put = AsyncMock(return_value=mock_update_response)

        mock_cls = MagicMock()
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", mock_cls):
            url = await create_and_write_sheet(
                user_id=1,
                title="Test Sheet",
                header=["Name", "Email"],
                rows=[["John", "john@example.com"], ["Jane", "jane@example.com"]],
            )

        assert url == "https://docs.google.com/spreadsheets/d/new_sheet_id_123"

        mock_refresh_token.assert_called_once_with(1)

        mock_client.post.assert_called_once()
        create_call = mock_client.post.call_args
        assert SHEETS_API_BASE in create_call[0][0]
        assert create_call[1]["headers"]["Authorization"] == "Bearer access_token_123"
        assert create_call[1]["json"]["properties"]["title"] == "Test Sheet"

        mock_client.put.assert_called_once()
        update_call = mock_client.put.call_args
        assert "new_sheet_id_123" in update_call[0][0]
        assert "values" in update_call[0][0]
        assert update_call[1]["headers"]["Authorization"] == "Bearer access_token_123"
        assert update_call[1]["params"]["valueInputOption"] == "RAW"


class TestFetchSheetRows:
    """Test fetch_sheet_rows function."""

    @pytest.mark.asyncio
    @patch("services.google_sheets.refresh_access_token")
    async def test_returns_rows(self, mock_refresh_token):
        """Test that sheet rows are fetched and returned."""
        mock_refresh_token.return_value = "access_token_123"

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "values": [
                ["Header1", "Header2"],
                ["Value1", "Value2"],
                ["Value3", "Value4"],
            ]
        }

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        mock_cls = MagicMock()
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", mock_cls):
            rows = await fetch_sheet_rows(
                user_id=1,
                spreadsheet_id="sheet_id_123",
                sheet_range="Sheet1",
            )

        assert len(rows) == 3
        assert rows[0] == ["Header1", "Header2"]
        assert rows[1] == ["Value1", "Value2"]
        assert rows[2] == ["Value3", "Value4"]

        mock_refresh_token.assert_called_once_with(1)

        mock_client.get.assert_called_once()
        get_call = mock_client.get.call_args
        assert "sheet_id_123" in get_call[0][0]
        assert "values" in get_call[0][0]
        assert "Sheet1" in get_call[0][0]
        assert get_call[1]["headers"]["Authorization"] == "Bearer access_token_123"

    @pytest.mark.asyncio
    @patch("services.google_sheets.refresh_access_token")
    async def test_default_sheet_range(self, mock_refresh_token):
        """Test that default sheet range is Sheet1."""
        mock_refresh_token.return_value = "token"

        mock_response = MagicMock()
        mock_response.json.return_value = {"values": []}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        mock_cls = MagicMock()
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", mock_cls):
            await fetch_sheet_rows(user_id=1, spreadsheet_id="id123")

        get_call = mock_client.get.call_args
        assert "Sheet1" in get_call[0][0]
