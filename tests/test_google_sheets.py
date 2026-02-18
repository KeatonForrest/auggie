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
    _sheets_request,
    GOOGLE_AUTH_URL,
    GOOGLE_TOKEN_URL,
    SHEETS_API_BASE,
    SCOPES,
    GoogleSheetsError,
    GoogleIntegrationMissing,
    GoogleTokenRevoked,
    GoogleTokenUnrecoverable,
    GoogleScopeInsufficient,
    GoogleSheetAccessDenied,
    GoogleSheetNotFound,
)
import httpx


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
        mock_response.raise_for_status = MagicMock()

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

    @pytest.mark.asyncio
    @patch("services.google_sheets.get_settings")
    async def test_http_error_raises(self, mock_get_settings):
        """Test that HTTP error raises GoogleSheetsError with oauth_token_exchange_failed."""
        mock_settings = MagicMock()
        mock_settings.google_client_id = "cid"
        mock_settings.google_client_secret = "csec"
        mock_settings.app_url = "https://example.com"
        mock_get_settings.return_value = mock_settings

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Bad Request", request=MagicMock(), response=mock_response
        )

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        mock_cls = MagicMock()
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", mock_cls):
            with pytest.raises(GoogleSheetsError) as exc_info:
                await exchange_code("bad_code")
            assert exc_info.value.code == "oauth_token_exchange_failed"

    @pytest.mark.asyncio
    @patch("services.google_sheets.get_settings")
    async def test_network_error_raises(self, mock_get_settings):
        """Test that network error raises GoogleSheetsError with oauth_token_exchange_failed."""
        mock_settings = MagicMock()
        mock_settings.google_client_id = "cid"
        mock_settings.google_client_secret = "csec"
        mock_settings.app_url = "https://example.com"
        mock_get_settings.return_value = mock_settings

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))

        mock_cls = MagicMock()
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", mock_cls):
            with pytest.raises(GoogleSheetsError) as exc_info:
                await exchange_code("code")
            assert exc_info.value.code == "oauth_token_exchange_failed"


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
        mock_response.raise_for_status = MagicMock()

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
    async def test_not_connected_raises_integration_missing(self, mock_get_integration):
        """Test that GoogleIntegrationMissing is raised when integration doesn't exist."""
        mock_get_integration.return_value = None

        with pytest.raises(GoogleIntegrationMissing):
            await refresh_access_token(1)

        mock_get_integration.assert_called_once_with(1, "google_sheets")

    @pytest.mark.asyncio
    @patch("services.google_sheets.get_settings")
    @patch("services.google_sheets.get_integration")
    async def test_revoked_token(self, mock_get_integration, mock_get_settings):
        """Test that invalid_grant response raises GoogleTokenRevoked."""
        past_time = datetime.now(timezone.utc) - timedelta(hours=1)
        mock_get_integration.return_value = {
            "access_token": "old", "refresh_token": "rt", "token_expires_at": past_time,
        }
        mock_get_settings.return_value = MagicMock(google_client_id="cid", google_client_secret="cs")

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = '{"error": "invalid_grant"}'
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Bad Request", request=MagicMock(), response=mock_response
        )

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        mock_cls = MagicMock()
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", mock_cls):
            with pytest.raises(GoogleTokenRevoked):
                await refresh_access_token(1)

    @pytest.mark.asyncio
    @patch("services.google_sheets.get_integration")
    async def test_no_refresh_token(self, mock_get_integration):
        """Test that missing refresh_token raises GoogleTokenRevoked."""
        past_time = datetime.now(timezone.utc) - timedelta(hours=1)
        mock_get_integration.return_value = {
            "access_token": "old", "refresh_token": None, "token_expires_at": past_time,
        }

        with pytest.raises(GoogleTokenRevoked):
            await refresh_access_token(1)

    @pytest.mark.asyncio
    @patch("services.google_sheets.get_settings")
    @patch("services.google_sheets.get_integration")
    async def test_other_refresh_error(self, mock_get_integration, mock_get_settings):
        """Test that non-invalid_grant HTTP error raises GoogleTokenUnrecoverable."""
        past_time = datetime.now(timezone.utc) - timedelta(hours=1)
        mock_get_integration.return_value = {
            "access_token": "old", "refresh_token": "rt", "token_expires_at": past_time,
        }
        mock_get_settings.return_value = MagicMock(google_client_id="cid", google_client_secret="cs")

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server Error", request=MagicMock(), response=mock_response
        )

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        mock_cls = MagicMock()
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", mock_cls):
            with pytest.raises(GoogleTokenUnrecoverable):
                await refresh_access_token(1)

    @pytest.mark.asyncio
    @patch("services.google_sheets.get_settings")
    @patch("services.google_sheets.get_integration")
    async def test_network_error_during_refresh(self, mock_get_integration, mock_get_settings):
        """Test that network error during refresh raises GoogleTokenUnrecoverable."""
        past_time = datetime.now(timezone.utc) - timedelta(hours=1)
        mock_get_integration.return_value = {
            "access_token": "old", "refresh_token": "rt", "token_expires_at": past_time,
        }
        mock_get_settings.return_value = MagicMock(google_client_id="cid", google_client_secret="cs")

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))

        mock_cls = MagicMock()
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", mock_cls):
            with pytest.raises(GoogleTokenUnrecoverable):
                await refresh_access_token(1)


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


class TestSheetsRequest:
    """Test _sheets_request helper."""

    @pytest.mark.asyncio
    @patch("services.google_sheets.refresh_access_token")
    async def test_401_refresh_retry_success(self, mock_refresh):
        """Test that 401 triggers refresh and retry, succeeding on second attempt."""
        mock_refresh.return_value = "new_token"

        resp_401 = MagicMock()
        resp_401.status_code = 401

        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.json.return_value = {"ok": True}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[resp_401, resp_200])

        result = await _sheets_request(mock_client, "get", "https://example.com", "old_token", 1, "test_op")
        assert result.status_code == 200
        mock_refresh.assert_called_once_with(1)
        assert mock_client.get.call_count == 2

    @pytest.mark.asyncio
    @patch("services.google_sheets.refresh_access_token")
    async def test_401_then_401_unrecoverable(self, mock_refresh):
        """Test that 401 after refresh raises GoogleTokenUnrecoverable."""
        mock_refresh.return_value = "new_token"

        resp_401 = MagicMock()
        resp_401.status_code = 401

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=resp_401)

        with pytest.raises(GoogleTokenUnrecoverable):
            await _sheets_request(mock_client, "get", "https://example.com", "token", 1, "test_op")

    @pytest.mark.asyncio
    async def test_403_insufficient_permissions(self):
        """Test that 403 with insufficientPermissions raises GoogleScopeInsufficient."""
        resp = MagicMock()
        resp.status_code = 403
        resp.text = '{"error": {"errors": [{"reason": "insufficientPermissions"}]}}'

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=resp)

        with pytest.raises(GoogleScopeInsufficient):
            await _sheets_request(mock_client, "get", "https://example.com", "token", 1, "test_op")

    @pytest.mark.asyncio
    async def test_403_sharing_denied(self):
        """Test that 403 without insufficientPermissions raises GoogleSheetAccessDenied."""
        resp = MagicMock()
        resp.status_code = 403
        resp.text = '{"error": {"message": "The caller does not have permission"}}'

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=resp)

        with pytest.raises(GoogleSheetAccessDenied):
            await _sheets_request(mock_client, "get", "https://example.com", "token", 1, "test_op")

    @pytest.mark.asyncio
    async def test_404_sheet_not_found(self):
        """Test that 404 raises GoogleSheetNotFound."""
        resp = MagicMock()
        resp.status_code = 404
        resp.text = "Not Found"

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=resp)

        with pytest.raises(GoogleSheetNotFound):
            await _sheets_request(mock_client, "get", "https://example.com", "token", 1, "test_op")

    @pytest.mark.asyncio
    async def test_500_generic_api_error(self):
        """Test that other non-2xx raises GoogleSheetsError with google_sheets_api_error."""
        resp = MagicMock()
        resp.status_code = 500
        resp.text = "Internal Server Error"

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=resp)

        with pytest.raises(GoogleSheetsError) as exc_info:
            await _sheets_request(mock_client, "get", "https://example.com", "token", 1, "test_op")
        assert exc_info.value.code == "google_sheets_api_error"


class TestCreateAndWriteSheet:
    """Test create_and_write_sheet function."""

    @pytest.mark.asyncio
    @patch("services.google_sheets.refresh_access_token")
    async def test_creates_and_writes_returns_url(self, mock_refresh_token):
        """Test that a spreadsheet is created, data is written, and URL is returned."""
        mock_refresh_token.return_value = "access_token_123"

        mock_create_response = MagicMock()
        mock_create_response.status_code = 200
        mock_create_response.json.return_value = {
            "spreadsheetId": "new_sheet_id_123",
            "spreadsheetUrl": "https://docs.google.com/spreadsheets/d/new_sheet_id_123",
        }

        mock_update_response = MagicMock()
        mock_update_response.status_code = 200
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

    @pytest.mark.asyncio
    @patch("services.google_sheets.get_integration")
    async def test_integration_missing(self, mock_get_integration):
        """Test that GoogleIntegrationMissing is raised when no integration."""
        mock_get_integration.return_value = None

        with pytest.raises(GoogleIntegrationMissing):
            await create_and_write_sheet(1, "Title", ["H"], [["R"]])


class TestFetchSheetRows:
    """Test fetch_sheet_rows function."""

    @pytest.mark.asyncio
    @patch("services.google_sheets.refresh_access_token")
    async def test_returns_rows(self, mock_refresh_token):
        """Test that sheet rows are fetched and returned."""
        mock_refresh_token.return_value = "access_token_123"

        mock_response = MagicMock()
        mock_response.status_code = 200
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

    @pytest.mark.asyncio
    @patch("services.google_sheets.refresh_access_token")
    async def test_default_sheet_range(self, mock_refresh_token):
        """Test that default sheet range is Sheet1."""
        mock_refresh_token.return_value = "token"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"values": []}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        mock_cls = MagicMock()
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", mock_cls):
            await fetch_sheet_rows(user_id=1, spreadsheet_id="id123")

        get_call = mock_client.get.call_args
        # The URL should contain Sheet1 — passed as positional arg or in headers
        assert "Sheet1" in str(get_call)

    @pytest.mark.asyncio
    @patch("services.google_sheets.get_integration")
    async def test_integration_missing(self, mock_get_integration):
        """Test that GoogleIntegrationMissing is raised when no integration."""
        mock_get_integration.return_value = None

        with pytest.raises(GoogleIntegrationMissing):
            await fetch_sheet_rows(1, "sheet_id")


class TestOAuthCallback:
    """Test _oauth_callback from routes/_helpers.py."""

    @pytest.mark.asyncio
    async def test_missing_code_400(self):
        """Test that missing code returns 400 with oauth_callback_missing_code."""
        from routes._helpers import _oauth_callback
        from fastapi import HTTPException

        request = MagicMock()
        request.query_params = {"state": "abc"}
        request.session = {"_google_sheets_state_": "abc"}

        with pytest.raises(HTTPException) as exc_info:
            await _oauth_callback(request, {"id": 1}, "google_sheets", AsyncMock())
        assert exc_info.value.status_code == 400
        assert exc_info.value.detail["code"] == "oauth_callback_missing_code"

    @pytest.mark.asyncio
    async def test_state_mismatch_400(self):
        """Test that state mismatch returns 400 with oauth_state_invalid."""
        from routes._helpers import _oauth_callback
        from fastapi import HTTPException

        request = MagicMock()
        request.query_params = {"code": "auth_code", "state": "wrong"}
        request.session = {"_google_sheets_state_": "expected"}

        with pytest.raises(HTTPException) as exc_info:
            await _oauth_callback(request, {"id": 1}, "google_sheets", AsyncMock())
        assert exc_info.value.status_code == 400
        assert exc_info.value.detail["code"] == "oauth_state_invalid"

    @pytest.mark.asyncio
    async def test_exchange_failure_502(self):
        """Test that exchange_code failure returns 502 with oauth_token_exchange_failed."""
        from routes._helpers import _oauth_callback
        from fastapi import HTTPException

        request = MagicMock()
        request.query_params = {"code": "auth_code", "state": "valid_state"}
        request.session = {"_google_sheets_state_": "valid_state"}

        mock_exchange = AsyncMock(side_effect=Exception("Network error"))

        with pytest.raises(HTTPException) as exc_info:
            await _oauth_callback(request, {"id": 1}, "google_sheets", mock_exchange)
        assert exc_info.value.status_code == 502
        assert exc_info.value.detail["code"] == "oauth_token_exchange_failed"


class TestRefreshTokenPreservation:
    """Test that refresh_access_token preserves the stored refresh token."""

    @pytest.mark.asyncio
    @patch("services.google_sheets.update_integration_tokens")
    @patch("services.google_sheets.get_settings")
    @patch("services.google_sheets.get_integration")
    async def test_refresh_preserves_stored_token_when_google_omits_it(
        self, mock_get_integration, mock_get_settings, mock_update_tokens
    ):
        """Google typically omits refresh_token on refresh grants.
        We must keep the original value instead of writing None."""
        past_time = datetime.now(timezone.utc) - timedelta(hours=1)
        mock_get_integration.return_value = {
            "access_token": "old_token",
            "refresh_token": "original_refresh_token",
            "token_expires_at": past_time,
        }
        mock_get_settings.return_value = MagicMock(
            google_client_id="cid", google_client_secret="cs"
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "new_access",
            "expires_in": 3600,
            # refresh_token intentionally absent — Google's normal behaviour
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        mock_cls = MagicMock()
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", mock_cls):
            token = await refresh_access_token(1)

        assert token == "new_access"
        mock_update_tokens.assert_called_once()
        call_kwargs = mock_update_tokens.call_args[1]
        assert call_kwargs["refresh_token"] == "original_refresh_token"

    @pytest.mark.asyncio
    @patch("services.google_sheets.update_integration_tokens")
    @patch("services.google_sheets.get_settings")
    @patch("services.google_sheets.get_integration")
    async def test_refresh_uses_new_token_when_google_provides_one(
        self, mock_get_integration, mock_get_settings, mock_update_tokens
    ):
        """When Google does return a new refresh_token, we should use it."""
        past_time = datetime.now(timezone.utc) - timedelta(hours=1)
        mock_get_integration.return_value = {
            "access_token": "old_token",
            "refresh_token": "original_refresh_token",
            "token_expires_at": past_time,
        }
        mock_get_settings.return_value = MagicMock(
            google_client_id="cid", google_client_secret="cs"
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "new_access",
            "refresh_token": "rotated_refresh_token",
            "expires_in": 3600,
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        mock_cls = MagicMock()
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", mock_cls):
            token = await refresh_access_token(1)

        assert token == "new_access"
        call_kwargs = mock_update_tokens.call_args[1]
        assert call_kwargs["refresh_token"] == "rotated_refresh_token"


class TestImportGoogleSheetRoute:
    """Route-level tests for POST /lists/import-google-sheet."""

    @pytest.mark.asyncio
    async def test_invalid_spreadsheet_url_returns_400(self, authed_client):
        """Invalid Google Sheets URL returns 400 with invalid_spreadsheet_url."""
        with patch("api.ratelimit.upload_limiter", MagicMock(check=MagicMock())):
            response = await authed_client.post(
                "/lists/import-google-sheet",
                json={"url": "https://not-a-sheet.com/foo", "list_name": "Test"},
            )
        assert response.status_code == 400
        data = response.json()
        assert data["error"]["code"] == "invalid_spreadsheet_url"

    @pytest.mark.asyncio
    async def test_sheet_not_found_returns_404(self, authed_client):
        """GoogleSheetNotFound propagates as 404 with sheet_not_found."""
        with patch("api.ratelimit.upload_limiter", MagicMock(check=MagicMock())), \
             patch("services.google_sheets.refresh_access_token", new_callable=AsyncMock, return_value="tok"), \
             patch("services.google_sheets._sheets_request", new_callable=AsyncMock, side_effect=GoogleSheetNotFound()):
            response = await authed_client.post(
                "/lists/import-google-sheet",
                json={"url": "https://docs.google.com/spreadsheets/d/abc123/edit", "list_name": "Test"},
            )
        assert response.status_code == 404
        data = response.json()
        assert data["error"]["code"] == "sheet_not_found"

    @pytest.mark.asyncio
    async def test_sheet_access_denied_returns_403(self, authed_client):
        """GoogleSheetAccessDenied propagates as 403 with sheet_access_denied."""
        with patch("api.ratelimit.upload_limiter", MagicMock(check=MagicMock())), \
             patch("services.google_sheets.refresh_access_token", new_callable=AsyncMock, return_value="tok"), \
             patch("services.google_sheets._sheets_request", new_callable=AsyncMock, side_effect=GoogleSheetAccessDenied()):
            response = await authed_client.post(
                "/lists/import-google-sheet",
                json={"url": "https://docs.google.com/spreadsheets/d/abc123/edit", "list_name": "Test"},
            )
        assert response.status_code == 403
        data = response.json()
        assert data["error"]["code"] == "sheet_access_denied"

    @pytest.mark.asyncio
    async def test_integration_missing_returns_400(self, authed_client):
        """GoogleIntegrationMissing propagates as 400 with google_integration_missing."""
        with patch("api.ratelimit.upload_limiter", MagicMock(check=MagicMock())), \
             patch("services.google_sheets.get_integration", new_callable=AsyncMock, return_value=None):
            response = await authed_client.post(
                "/lists/import-google-sheet",
                json={"url": "https://docs.google.com/spreadsheets/d/abc123/edit", "list_name": "Test"},
            )
        assert response.status_code == 400
        data = response.json()
        assert data["error"]["code"] == "google_integration_missing"

    @pytest.mark.asyncio
    async def test_scope_insufficient_returns_403(self, authed_client):
        """GoogleScopeInsufficient propagates as 403 with google_scope_insufficient."""
        with patch("api.ratelimit.upload_limiter", MagicMock(check=MagicMock())), \
             patch("services.google_sheets.refresh_access_token", new_callable=AsyncMock, return_value="tok"), \
             patch("services.google_sheets._sheets_request", new_callable=AsyncMock, side_effect=GoogleScopeInsufficient()):
            response = await authed_client.post(
                "/lists/import-google-sheet",
                json={"url": "https://docs.google.com/spreadsheets/d/abc123/edit", "list_name": "Test"},
            )
        assert response.status_code == 403
        data = response.json()
        assert data["error"]["code"] == "google_scope_insufficient"


class TestPushToSheetsRoute:
    """Route-level tests for POST /lists/{list_id}/push-to-sheets."""

    @pytest.mark.asyncio
    async def test_integration_missing_returns_400(self, authed_client):
        """Missing Google integration returns 400 with google_integration_missing."""
        with patch("routes.lists.get_list", new_callable=AsyncMock, return_value={"id": 1, "name": "Test"}), \
             patch("routes.lists.get_integration", new_callable=AsyncMock, return_value=None):
            response = await authed_client.post("/lists/1/push-to-sheets", json={})
        assert response.status_code == 400
        data = response.json()
        assert data["error"]["code"] == "google_integration_missing"

    @pytest.mark.asyncio
    async def test_token_revoked_returns_401(self, authed_client):
        """GoogleTokenRevoked propagates as 401 with google_token_revoked."""
        with patch("routes.lists.get_list", new_callable=AsyncMock, return_value={"id": 1, "name": "Test"}), \
             patch("routes.lists.get_integration", new_callable=AsyncMock, return_value={"provider": "google_sheets"}), \
             patch("routes.lists.get_list_accounts", new_callable=AsyncMock, return_value=[]), \
             patch("routes.lists.get_outreach_drafts_batch", new_callable=AsyncMock, return_value={}), \
             patch("services.google_sheets.refresh_access_token", new_callable=AsyncMock, side_effect=GoogleTokenRevoked()):
            response = await authed_client.post("/lists/1/push-to-sheets", json={})
        assert response.status_code == 401
        data = response.json()
        assert data["error"]["code"] == "google_token_revoked"

    @pytest.mark.asyncio
    async def test_sheet_api_error_returns_502(self, authed_client):
        """Generic GoogleSheetsError propagates as 502."""
        with patch("routes.lists.get_list", new_callable=AsyncMock, return_value={"id": 1, "name": "Test"}), \
             patch("routes.lists.get_integration", new_callable=AsyncMock, return_value={"provider": "google_sheets"}), \
             patch("routes.lists.get_list_accounts", new_callable=AsyncMock, return_value=[]), \
             patch("routes.lists.get_outreach_drafts_batch", new_callable=AsyncMock, return_value={}), \
             patch("services.google_sheets.refresh_access_token", new_callable=AsyncMock, return_value="tok"), \
             patch("services.google_sheets._sheets_request", new_callable=AsyncMock, side_effect=GoogleSheetsError("google_sheets_api_error", "Google Sheets API error. Please try again.", 502)):
            response = await authed_client.post("/lists/1/push-to-sheets", json={})
        assert response.status_code == 502
        data = response.json()
        assert data["error"]["code"] == "google_sheets_api_error"
