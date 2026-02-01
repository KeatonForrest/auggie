"""Tests for services/dns_analyzer.py"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class FakeNSRecord:
    def __init__(self, host):
        self.host = host


class FakeMXRecord:
    def __init__(self, host):
        self.host = host


class FakeTXTRecord:
    def __init__(self, text):
        self.text = text


@pytest.fixture
def mock_resolver():
    resolver = AsyncMock()
    resolver.query = AsyncMock(return_value=[])
    return resolver


class TestDNSAnalyzer:
    @pytest.mark.asyncio
    async def test_ns_provider_aws(self, mock_resolver):
        mock_resolver.query = AsyncMock(side_effect=lambda name, qtype: {
            ("example.com", "NS"): [FakeNSRecord("ns-123.awsdns-45.com")],
            ("example.com", "MX"): [],
            ("example.com", "TXT"): [],
            ("_dmarc.example.com", "TXT"): [],
        }.get((name, qtype), []))

        with patch("services.dns_analyzer.aiodns.DNSResolver", return_value=mock_resolver):
            from services.dns_analyzer import DNSAnalyzer
            analyzer = DNSAnalyzer()
            profile = await analyzer.analyze("example.com")
        assert profile.ns_provider == "AWS"
        assert "AWS" in profile.cloud_provider_hints

    @pytest.mark.asyncio
    async def test_mx_provider_google(self, mock_resolver):
        mock_resolver.query = AsyncMock(side_effect=lambda name, qtype: {
            ("example.com", "NS"): [],
            ("example.com", "MX"): [FakeMXRecord("aspmx.l.google.com")],
            ("example.com", "TXT"): [],
            ("_dmarc.example.com", "TXT"): [],
        }.get((name, qtype), []))

        with patch("services.dns_analyzer.aiodns.DNSResolver", return_value=mock_resolver):
            from services.dns_analyzer import DNSAnalyzer
            analyzer = DNSAnalyzer()
            profile = await analyzer.analyze("example.com")
        assert profile.mx_provider == "Google Workspace"

    @pytest.mark.asyncio
    async def test_spf_dmarc_detection(self, mock_resolver):
        mock_resolver.query = AsyncMock(side_effect=lambda name, qtype: {
            ("example.com", "NS"): [],
            ("example.com", "MX"): [],
            ("example.com", "TXT"): [FakeTXTRecord("v=spf1 include:_spf.google.com ~all")],
            ("_dmarc.example.com", "TXT"): [FakeTXTRecord("v=DMARC1; p=reject; rua=mailto:d@example.com")],
        }.get((name, qtype), []))

        with patch("services.dns_analyzer.aiodns.DNSResolver", return_value=mock_resolver):
            from services.dns_analyzer import DNSAnalyzer
            analyzer = DNSAnalyzer()
            profile = await analyzer.analyze("example.com")
        assert profile.has_spf is True
        assert profile.has_dmarc is True
        assert profile.dmarc_policy == "reject"

    @pytest.mark.asyncio
    async def test_error_handling(self, mock_resolver):
        import aiodns
        mock_resolver.query = AsyncMock(side_effect=aiodns.error.DNSError())

        with patch("services.dns_analyzer.aiodns.DNSResolver", return_value=mock_resolver):
            from services.dns_analyzer import DNSAnalyzer
            analyzer = DNSAnalyzer()
            profile = await analyzer.analyze("nonexistent.example.com")
        assert profile.domain == "nonexistent.example.com"
        assert profile.ns_provider is None

    @pytest.mark.asyncio
    async def test_ns_cloudflare(self, mock_resolver):
        mock_resolver.query = AsyncMock(side_effect=lambda name, qtype: {
            ("example.com", "NS"): [FakeNSRecord("elsa.ns.cloudflare.com")],
            ("example.com", "MX"): [],
            ("example.com", "TXT"): [],
            ("_dmarc.example.com", "TXT"): [],
        }.get((name, qtype), []))

        with patch("services.dns_analyzer.aiodns.DNSResolver", return_value=mock_resolver):
            from services.dns_analyzer import DNSAnalyzer
            analyzer = DNSAnalyzer()
            profile = await analyzer.analyze("example.com")
        assert profile.ns_provider == "Cloudflare"

    @pytest.mark.asyncio
    async def test_mx_microsoft(self, mock_resolver):
        mock_resolver.query = AsyncMock(side_effect=lambda name, qtype: {
            ("example.com", "NS"): [],
            ("example.com", "MX"): [FakeMXRecord("example-com.mail.protection.outlook.com")],
            ("example.com", "TXT"): [],
            ("_dmarc.example.com", "TXT"): [],
        }.get((name, qtype), []))

        with patch("services.dns_analyzer.aiodns.DNSResolver", return_value=mock_resolver):
            from services.dns_analyzer import DNSAnalyzer
            analyzer = DNSAnalyzer()
            profile = await analyzer.analyze("example.com")
        assert profile.mx_provider == "Microsoft 365"
