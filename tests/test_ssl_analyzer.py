"""Tests for services/ssl_analyzer.py"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta, timezone


MOCK_CERT = {
    "issuer": ((("organizationName", "Let's Encrypt"),),),
    "notAfter": (datetime.now() + timedelta(days=60)).strftime("%b %d %H:%M:%S %Y GMT"),
    "subjectAltName": (("DNS", "example.com"), ("DNS", "*.example.com")),
}


class TestSSLAnalyzer:
    @pytest.mark.asyncio
    async def test_basic_cert_parsing(self):
        mock_ssl_obj = MagicMock()
        mock_ssl_obj.getpeercert.return_value = MOCK_CERT

        mock_writer = MagicMock()
        mock_writer.get_extra_info.return_value = mock_ssl_obj
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        with patch("services.ssl_analyzer.asyncio.open_connection", new_callable=AsyncMock, return_value=(MagicMock(), mock_writer)):
            from services.ssl_analyzer import SSLAnalyzer
            analyzer = SSLAnalyzer()
            profile = await analyzer.analyze("example.com")

        assert profile.issuer == "Let's Encrypt"
        assert profile.automation_inferred is True
        assert profile.is_wildcard is True
        assert profile.san_count == 2
        assert profile.expiry_days is not None and profile.expiry_days > 50

    @pytest.mark.asyncio
    async def test_expiry_calculation(self):
        cert = {
            "issuer": ((("organizationName", "DigiCert"),),),
            "notAfter": (datetime.now() + timedelta(days=15)).strftime("%b %d %H:%M:%S %Y GMT"),
            "subjectAltName": (("DNS", "example.com"),),
        }
        mock_ssl_obj = MagicMock()
        mock_ssl_obj.getpeercert.return_value = cert
        mock_writer = MagicMock()
        mock_writer.get_extra_info.return_value = mock_ssl_obj
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        with patch("services.ssl_analyzer.asyncio.open_connection", new_callable=AsyncMock, return_value=(MagicMock(), mock_writer)):
            from services.ssl_analyzer import SSLAnalyzer
            analyzer = SSLAnalyzer()
            profile = await analyzer.analyze("example.com")

        assert profile.issuer == "DigiCert"
        assert profile.automation_inferred is False
        assert profile.expiry_days is not None and profile.expiry_days < 20

    @pytest.mark.asyncio
    async def test_connection_refused(self):
        with patch("services.ssl_analyzer.asyncio.open_connection", new_callable=AsyncMock, side_effect=ConnectionRefusedError):
            from services.ssl_analyzer import SSLAnalyzer
            analyzer = SSLAnalyzer()
            profile = await analyzer.analyze("nossl.example.com")
        assert profile.domain == "nossl.example.com"
        assert profile.issuer is None

    @pytest.mark.asyncio
    async def test_timeout(self):
        import asyncio
        with patch("services.ssl_analyzer.asyncio.open_connection", new_callable=AsyncMock, side_effect=asyncio.TimeoutError):
            from services.ssl_analyzer import SSLAnalyzer
            analyzer = SSLAnalyzer()
            profile = await analyzer.analyze("slow.example.com")
        assert profile.issuer is None

    @pytest.mark.asyncio
    async def test_no_wildcard(self):
        cert = {
            "issuer": ((("organizationName", "Sectigo"),),),
            "notAfter": (datetime.now() + timedelta(days=90)).strftime("%b %d %H:%M:%S %Y GMT"),
            "subjectAltName": (("DNS", "example.com"), ("DNS", "www.example.com")),
        }
        mock_ssl_obj = MagicMock()
        mock_ssl_obj.getpeercert.return_value = cert
        mock_writer = MagicMock()
        mock_writer.get_extra_info.return_value = mock_ssl_obj
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        with patch("services.ssl_analyzer.asyncio.open_connection", new_callable=AsyncMock, return_value=(MagicMock(), mock_writer)):
            from services.ssl_analyzer import SSLAnalyzer
            analyzer = SSLAnalyzer()
            profile = await analyzer.analyze("example.com")

        assert profile.is_wildcard is False
        assert profile.automation_inferred is False
