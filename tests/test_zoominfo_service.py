"""
test_zoominfo_service.py - Tests for ZoomInfo integration service.
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch, MagicMock

import httpx


class TestZoomInfoPkcePair:
    def test_generates_pair(self):
        from services.zoominfo import generate_pkce_pair
        verifier, challenge = generate_pkce_pair()
        assert len(verifier) > 40
        assert len(challenge) > 20
        assert verifier != challenge

    def test_deterministic_challenge(self):
        import base64, hashlib
        from services.zoominfo import generate_pkce_pair
        verifier, challenge = generate_pkce_pair()
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        assert challenge == expected


class TestZoomInfoAuthorizeUrl:
    def test_builds_correct_url(self):
        from services.zoominfo import get_authorize_url, ZOOMINFO_LOGIN_URL

        with patch("services.zoominfo.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                zoominfo_client_id="zi-client",
                app_url="https://app.example.com",
            )
            url = get_authorize_url("state-123", "challenge-abc")

        assert url.startswith(ZOOMINFO_LOGIN_URL)
        assert "client_id=zi-client" in url
        assert "state=state-123" in url
        assert "code_challenge=challenge-abc" in url
        assert "code_challenge_method=S256" in url
        assert "response_type=code" in url


class TestZoomInfoExchangeCode:
    @pytest.mark.asyncio
    async def test_exchanges_code(self):
        from services.zoominfo import exchange_code

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"access_token": "zi-token", "refresh_token": "zi-rt", "expires_in": 86400}
        mock_resp.raise_for_status = MagicMock()

        with patch("services.zoominfo.get_settings") as mock_settings, \
             patch("httpx.AsyncClient") as mock_cls:
            mock_settings.return_value = MagicMock(
                zoominfo_client_id="cid", zoominfo_client_secret="csecret",
                app_url="https://app.example.com",
            )
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await exchange_code("auth-code", "verifier-123")

        assert result["access_token"] == "zi-token"
        call_data = mock_client.post.call_args[1]["data"]
        assert call_data["code"] == "auth-code"
        assert call_data["code_verifier"] == "verifier-123"


class TestZoomInfoTokenRefresh:
    @pytest.mark.asyncio
    async def test_returns_valid_token(self):
        from services.zoominfo import refresh_access_token

        future = datetime.now(timezone.utc) + timedelta(hours=2)
        with patch("services.zoominfo.get_integration", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {"access_token": "valid", "refresh_token": "rt", "token_expires_at": future}
            token = await refresh_access_token(1)

        assert token == "valid"

    @pytest.mark.asyncio
    async def test_refreshes_expired_token(self):
        from services.zoominfo import refresh_access_token

        past = datetime.now(timezone.utc) - timedelta(minutes=10)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"access_token": "new-token", "refresh_token": "new-rt", "expires_in": 86400}
        mock_resp.raise_for_status = MagicMock()

        with patch("services.zoominfo.get_integration", new_callable=AsyncMock) as mock_get, \
             patch("services.zoominfo.update_integration_tokens", new_callable=AsyncMock) as mock_update, \
             patch("services.zoominfo.get_settings") as mock_settings, \
             patch("httpx.AsyncClient") as mock_cls:
            mock_get.return_value = {"access_token": "expired", "refresh_token": "old-rt", "token_expires_at": past}
            mock_settings.return_value = MagicMock(zoominfo_client_id="cid", zoominfo_client_secret="csecret")
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            token = await refresh_access_token(1)

        assert token == "new-token"
        mock_update.assert_called_once()

    @pytest.mark.asyncio
    async def test_raises_when_not_connected(self):
        from services.zoominfo import refresh_access_token

        with patch("services.zoominfo.get_integration", new_callable=AsyncMock, return_value=None):
            with pytest.raises(RuntimeError, match="ZoomInfo not connected"):
                await refresh_access_token(1)


class TestZoomInfoSearchCompanies:
    @pytest.mark.asyncio
    async def test_returns_results(self):
        from services.zoominfo import search_companies

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "data": [
                {"id": "z1", "companyName": "Acme", "website": "acme.com", "employeeCount": 500, "revenue": 50000000, "city": "SF", "state": "CA", "country": "US"},
            ]
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("services.zoominfo.refresh_access_token", new_callable=AsyncMock, return_value="token"), \
             patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            results = await search_companies(1, "Acme")

        assert len(results) == 1
        assert results[0]["name"] == "Acme"
        assert results[0]["employeeCount"] == 500

    @pytest.mark.asyncio
    async def test_returns_empty_on_no_data(self):
        from services.zoominfo import search_companies

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": []}
        mock_resp.raise_for_status = MagicMock()

        with patch("services.zoominfo.refresh_access_token", new_callable=AsyncMock, return_value="token"), \
             patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            results = await search_companies(1, "NonExistent")

        assert results == []


class TestZoomInfoGetFirmographics:
    @pytest.mark.asyncio
    async def test_returns_none_when_not_connected(self):
        from services.zoominfo import get_firmographics

        with patch("services.zoominfo.get_integration", new_callable=AsyncMock, return_value=None):
            result = await get_firmographics(1, "https://acme.com")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_formatted_data(self):
        from services.zoominfo import get_firmographics

        with patch("services.zoominfo.get_integration", new_callable=AsyncMock, return_value={"access_token": "tok"}), \
             patch("services.zoominfo.search_companies", new_callable=AsyncMock, return_value=[
                 {"name": "Acme", "website": "acme.com", "employeeCount": 500, "revenue": 50000000, "city": "SF", "state": "CA", "country": "US"},
             ]):

            result = await get_firmographics(1, "https://acme.com")

        assert "Acme" in result
        assert "500" in result
        assert "SF" in result

    @pytest.mark.asyncio
    async def test_returns_none_when_no_results(self):
        from services.zoominfo import get_firmographics

        with patch("services.zoominfo.get_integration", new_callable=AsyncMock, return_value={"access_token": "tok"}), \
             patch("services.zoominfo.search_companies", new_callable=AsyncMock, return_value=[]):

            result = await get_firmographics(1, "https://acme.com")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_exception(self):
        from services.zoominfo import get_firmographics

        with patch("services.zoominfo.get_integration", new_callable=AsyncMock, side_effect=Exception("fail")):
            result = await get_firmographics(1, "https://acme.com")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_only_name(self):
        from services.zoominfo import get_firmographics

        with patch("services.zoominfo.get_integration", new_callable=AsyncMock, return_value={"access_token": "tok"}), \
             patch("services.zoominfo.search_companies", new_callable=AsyncMock, return_value=[
                 {"name": "Acme", "website": "acme.com"},
             ]):

            result = await get_firmographics(1, "https://acme.com")

        assert result is None

    @pytest.mark.asyncio
    async def test_matches_exact_domain(self):
        from services.zoominfo import get_firmographics

        with patch("services.zoominfo.get_integration", new_callable=AsyncMock, return_value={"access_token": "tok"}), \
             patch("services.zoominfo.search_companies", new_callable=AsyncMock, return_value=[
                 {"name": "Wrong Co", "website": "wrong.com", "employeeCount": 10},
                 {"name": "Acme", "website": "https://acme.com", "employeeCount": 500},
             ]):

            result = await get_firmographics(1, "https://acme.com")

        assert "Acme" in result
        assert "500" in result
