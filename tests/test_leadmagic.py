"""Tests for LeadMagic service."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.leadmagic import LeadMagicService


def _mock_httpx_client(mock_client):
    """Helper: patch httpx.AsyncClient as async context manager returning mock_client."""
    mock_cls = MagicMock()
    mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
    return patch("httpx.AsyncClient", mock_cls)


class TestConfiguration:
    def test_configured(self):
        with patch("services.leadmagic.get_settings") as m:
            m.return_value = MagicMock(leadmagic_api_key="key")
            assert LeadMagicService().is_configured() is True

    def test_not_configured(self):
        with patch("services.leadmagic.get_settings") as m:
            m.return_value = MagicMock(leadmagic_api_key=None)
            assert LeadMagicService().is_configured() is False


class TestFindRole:
    @pytest.mark.asyncio
    async def test_success(self):
        with patch("services.leadmagic.get_settings") as m:
            m.return_value = MagicMock(leadmagic_api_key="key")
            service = LeadMagicService()

        resp = MagicMock(status_code=200)
        resp.json.return_value = {
            "message": "Role Found", "name": "John Doe",
            "first_name": "John", "last_name": "Doe",
            "profile_url": "https://li.com/johndoe", "company_name": "Acme",
        }
        client = AsyncMock()
        client.post.return_value = resp

        with _mock_httpx_client(client):
            result = await service.find_role("acme.com", "CEO", "Acme")

        assert result["name"] == "John Doe"
        assert result["title"] == "CEO"

    @pytest.mark.asyncio
    async def test_not_configured(self):
        with patch("services.leadmagic.get_settings") as m:
            m.return_value = MagicMock(leadmagic_api_key=None)
            result = await LeadMagicService().find_role("x.com", "CEO")
        assert result is None

    @pytest.mark.asyncio
    async def test_not_found(self):
        with patch("services.leadmagic.get_settings") as m:
            m.return_value = MagicMock(leadmagic_api_key="key")
            service = LeadMagicService()

        resp = MagicMock(status_code=200)
        resp.json.return_value = {"message": "Role Not Found"}
        client = AsyncMock()
        client.post.return_value = resp

        with _mock_httpx_client(client):
            assert await service.find_role("x.com", "CTO") is None

    @pytest.mark.asyncio
    async def test_missing_name(self):
        with patch("services.leadmagic.get_settings") as m:
            m.return_value = MagicMock(leadmagic_api_key="key")
            service = LeadMagicService()

        resp = MagicMock(status_code=200)
        resp.json.return_value = {"message": "Role Found", "name": ""}
        client = AsyncMock()
        client.post.return_value = resp

        with _mock_httpx_client(client):
            assert await service.find_role("x.com", "CEO") is None

    @pytest.mark.asyncio
    async def test_http_error(self):
        with patch("services.leadmagic.get_settings") as m:
            m.return_value = MagicMock(leadmagic_api_key="key")
            service = LeadMagicService()

        resp = MagicMock(status_code=500, text="error")
        client = AsyncMock()
        client.post.return_value = resp

        with _mock_httpx_client(client):
            assert await service.find_role("x.com", "CEO") is None

    @pytest.mark.asyncio
    async def test_exception(self):
        with patch("services.leadmagic.get_settings") as m:
            m.return_value = MagicMock(leadmagic_api_key="key")
            service = LeadMagicService()

        client = AsyncMock()
        client.post.side_effect = Exception("network")

        with _mock_httpx_client(client):
            assert await service.find_role("x.com", "CEO") is None


class TestFindEmail:
    @pytest.mark.asyncio
    async def test_valid(self):
        with patch("services.leadmagic.get_settings") as m:
            m.return_value = MagicMock(leadmagic_api_key="key")
            service = LeadMagicService()

        resp = MagicMock(status_code=200)
        resp.json.return_value = {"email": "j@x.com", "status": "valid"}
        client = AsyncMock()
        client.post.return_value = resp

        with _mock_httpx_client(client):
            result = await service.find_email("John", "Doe", "x.com")
        assert result["email"] == "j@x.com"

    @pytest.mark.asyncio
    async def test_valid_catch_all(self):
        with patch("services.leadmagic.get_settings") as m:
            m.return_value = MagicMock(leadmagic_api_key="key")
            service = LeadMagicService()

        resp = MagicMock(status_code=200)
        resp.json.return_value = {"email": "j@x.com", "status": "valid_catch_all"}
        client = AsyncMock()
        client.post.return_value = resp

        with _mock_httpx_client(client):
            result = await service.find_email("John", "Doe", "x.com")
        assert result["status"] == "valid_catch_all"

    @pytest.mark.asyncio
    async def test_invalid_status(self):
        with patch("services.leadmagic.get_settings") as m:
            m.return_value = MagicMock(leadmagic_api_key="key")
            service = LeadMagicService()

        resp = MagicMock(status_code=200)
        resp.json.return_value = {"email": "j@x.com", "status": "invalid"}
        client = AsyncMock()
        client.post.return_value = resp

        with _mock_httpx_client(client):
            assert await service.find_email("John", "Doe", "x.com") is None

    @pytest.mark.asyncio
    async def test_not_configured(self):
        with patch("services.leadmagic.get_settings") as m:
            m.return_value = MagicMock(leadmagic_api_key=None)
            assert await LeadMagicService().find_email("J", "D", "x.com") is None

    @pytest.mark.asyncio
    async def test_exception(self):
        with patch("services.leadmagic.get_settings") as m:
            m.return_value = MagicMock(leadmagic_api_key="key")
            service = LeadMagicService()

        client = AsyncMock()
        client.post.side_effect = Exception("fail")

        with _mock_httpx_client(client):
            assert await service.find_email("J", "D", "x.com") is None


class TestEnrichContacts:
    @pytest.mark.asyncio
    async def test_mixed_results(self):
        with patch("services.leadmagic.get_settings") as m:
            m.return_value = MagicMock(leadmagic_api_key="key")
            service = LeadMagicService()

        async def mock_find_role(domain, title, company_name=""):
            if title == "CEO":
                return {"name": "John", "first_name": "John", "last_name": "Doe", "title": "CEO", "profile_url": "", "company_name": "Acme"}
            return None

        async def mock_find_email(first, last, domain):
            return {"email": "john@acme.com", "status": "valid"}

        service.find_role = AsyncMock(side_effect=mock_find_role)
        service.find_email = AsyncMock(side_effect=mock_find_email)

        result = await service.enrich_contacts("acme.com", "Acme", ["CEO", "CTO"])
        assert len(result) == 1
        assert result[0]["email"] == "john@acme.com"

    @pytest.mark.asyncio
    async def test_not_configured(self):
        with patch("services.leadmagic.get_settings") as m:
            m.return_value = MagicMock(leadmagic_api_key=None)
            result = await LeadMagicService().enrich_contacts("x.com", "X", ["CEO"])
        assert result == []

    @pytest.mark.asyncio
    async def test_no_roles_found(self):
        with patch("services.leadmagic.get_settings") as m:
            m.return_value = MagicMock(leadmagic_api_key="key")
            service = LeadMagicService()
        service.find_role = AsyncMock(return_value=None)
        result = await service.enrich_contacts("x.com", "X", ["CEO", "CTO"])
        assert result == []
        assert service.find_role.call_count == 2
