"""Tests for services/wappalyzer.py"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from models import TechStack, DetectedTechnology


@pytest.fixture
def mock_wappalyzer():
    wappalyzer = MagicMock()
    wappalyzer.analyze_with_versions_and_categories.return_value = {}
    return wappalyzer


@pytest.fixture
def wappalyzer_service(mock_wappalyzer):
    with patch("services.wappalyzer.WAPPALYZER_AVAILABLE", True), \
         patch("services.wappalyzer.Wappalyzer") as mock_cls:
        mock_cls.latest.return_value = mock_wappalyzer
        from services.wappalyzer import WappalyzerService
        service = WappalyzerService()
        return service


@pytest.fixture
def wappalyzer_service_unavailable():
    with patch("services.wappalyzer.WAPPALYZER_AVAILABLE", False):
        from services.wappalyzer import WappalyzerService
        service = WappalyzerService()
        return service


class TestParseTechnologies:
    def test_with_versions_and_categories(self, wappalyzer_service):
        results = {
            "React": {"versions": ["18.2.0"], "categories": ["JavaScript frameworks"]},
            "WordPress": {"versions": ["6.0"], "categories": ["CMS", "Blogs"]},
        }
        ts = wappalyzer_service._parse_technologies(results, "https://example.com")
        assert len(ts.technologies) == 2
        assert ts.scan_url == "https://example.com"
        # Sorted by category
        assert ts.technologies[0].name == "WordPress"
        assert ts.technologies[0].category == "CMS, Blogs"
        assert ts.technologies[1].name == "React"
        assert ts.technologies[1].version == "18.2.0"

    def test_without_versions(self, wappalyzer_service):
        results = {"Nginx": {"versions": [], "categories": ["Web servers"]}}
        ts = wappalyzer_service._parse_technologies(results, "https://x.com")
        assert ts.technologies[0].version is None

    def test_empty_results(self, wappalyzer_service):
        ts = wappalyzer_service._parse_technologies({}, "https://x.com")
        assert len(ts.technologies) == 0

    def test_without_categories(self, wappalyzer_service):
        results = {"Custom": {"versions": ["1.0"], "categories": []}}
        ts = wappalyzer_service._parse_technologies(results, "https://x.com")
        assert ts.technologies[0].category is None


class TestSyncAnalyzeUrl:
    def test_success(self, wappalyzer_service):
        with patch("services.wappalyzer.WebPage") as mock_wp:
            mock_wp.new_from_url.return_value = MagicMock()
            wappalyzer_service.wappalyzer.analyze_with_versions_and_categories.return_value = {
                "React": {"versions": ["18"], "categories": ["JS"]}
            }
            ts = wappalyzer_service._sync_analyze_url("https://example.com")
        assert len(ts.technologies) == 1
        assert ts.technologies[0].name == "React"

    def test_exception_returns_empty(self, wappalyzer_service):
        with patch("services.wappalyzer.WebPage") as mock_wp:
            mock_wp.new_from_url.side_effect = Exception("fail")
            ts = wappalyzer_service._sync_analyze_url("https://example.com")
        assert len(ts.technologies) == 0


class TestSyncAnalyzeHtml:
    def test_success(self, wappalyzer_service):
        with patch("services.wappalyzer.WebPage") as mock_wp:
            mock_wp.return_value = MagicMock()
            wappalyzer_service.wappalyzer.analyze_with_versions_and_categories.return_value = {
                "Bootstrap": {"versions": ["5"], "categories": ["UI"]}
            }
            ts = wappalyzer_service._sync_analyze_html("<html/>", "https://x.com", {})
        assert len(ts.technologies) == 1
        mock_wp.assert_called_once_with("https://x.com", "<html/>", {})

    def test_exception_returns_empty(self, wappalyzer_service):
        with patch("services.wappalyzer.WebPage") as mock_wp:
            mock_wp.side_effect = Exception("fail")
            ts = wappalyzer_service._sync_analyze_html("<html/>", "https://x.com", {})
        assert len(ts.technologies) == 0


class TestAnalyzeUrl:
    @pytest.mark.asyncio
    async def test_when_wappalyzer_none(self, wappalyzer_service_unavailable):
        ts = await wappalyzer_service_unavailable.analyze_url("https://x.com")
        assert len(ts.technologies) == 0

    @pytest.mark.asyncio
    async def test_exception_returns_empty(self, wappalyzer_service):
        with patch.object(wappalyzer_service, "_sync_analyze_url", side_effect=Exception("fail")):
            with patch("asyncio.get_event_loop") as mock_loop:
                mock_loop.return_value.run_in_executor = AsyncMock(side_effect=Exception("fail"))
                ts = await wappalyzer_service.analyze_url("https://x.com")
        assert len(ts.technologies) == 0


class TestAnalyzeHtml:
    @pytest.mark.asyncio
    async def test_when_wappalyzer_none(self, wappalyzer_service_unavailable):
        ts = await wappalyzer_service_unavailable.analyze_html("<html/>", "https://x.com")
        assert len(ts.technologies) == 0


class TestCheckUrlExists:
    @pytest.mark.asyncio
    async def test_head_success(self, wappalyzer_service):
        client = AsyncMock()
        resp = MagicMock(status_code=200, url="https://example.com/app")
        client.head.return_value = resp
        result = await wappalyzer_service._check_url_exists(client, "https://example.com/app")
        assert result == "https://example.com/app"

    @pytest.mark.asyncio
    async def test_head_404_returns_none(self, wappalyzer_service):
        client = AsyncMock()
        resp = MagicMock(status_code=404)
        client.head.return_value = resp
        result = await wappalyzer_service._check_url_exists(client, "https://example.com/app")
        assert result is None

    @pytest.mark.asyncio
    async def test_head_timeout_returns_none(self, wappalyzer_service):
        import httpx
        client = AsyncMock()
        client.head.side_effect = httpx.TimeoutException("timeout")
        result = await wappalyzer_service._check_url_exists(client, "https://example.com/app")
        assert result is None

    @pytest.mark.asyncio
    async def test_head_generic_error_get_fallback(self, wappalyzer_service):
        client = AsyncMock()
        client.head.side_effect = Exception("unknown")
        resp = MagicMock(status_code=200, url="https://example.com/app")
        client.get.return_value = resp
        result = await wappalyzer_service._check_url_exists(client, "https://example.com/app")
        assert result == "https://example.com/app"

    @pytest.mark.asyncio
    async def test_both_fail(self, wappalyzer_service):
        client = AsyncMock()
        client.head.side_effect = Exception("e")
        client.get.side_effect = Exception("fail")
        result = await wappalyzer_service._check_url_exists(client, "https://example.com/app")
        assert result is None


class TestValidateRedirect:
    def test_same_host(self):
        from services.wappalyzer import WappalyzerService
        resp = MagicMock(url="https://example.com/app/login")
        assert WappalyzerService._validate_redirect("https://example.com/app", resp) == "https://example.com/app"

    def test_different_host_bare_domain(self):
        from services.wappalyzer import WappalyzerService
        resp = MagicMock(url="https://other.com")
        assert WappalyzerService._validate_redirect("https://example.com/app", resp) is None

    def test_different_host_with_path(self):
        from services.wappalyzer import WappalyzerService
        resp = MagicMock(url="https://other.example.com/specific/page")
        result = WappalyzerService._validate_redirect("https://app.example.com", resp)
        # Final URL doesn't end in common TLD root, so it's accepted
        assert result == "https://app.example.com"


class TestDiscoverSubdomains:
    @pytest.mark.asyncio
    async def test_finds_some(self, wappalyzer_service):
        async def mock_check(client, url):
            return url if "app.example.com" in url else None

        with patch.object(wappalyzer_service, "_check_url_exists", side_effect=mock_check), \
             patch("services.wappalyzer.get_shared_http_client", new_callable=AsyncMock, return_value=AsyncMock()):
            urls = await wappalyzer_service.discover_subdomains("https://www.example.com")
        assert "https://app.example.com" in urls

    @pytest.mark.asyncio
    async def test_finds_none(self, wappalyzer_service):
        async def mock_check(client, url):
            return None

        with patch.object(wappalyzer_service, "_check_url_exists", side_effect=mock_check), \
             patch("services.wappalyzer.get_shared_http_client", new_callable=AsyncMock, return_value=AsyncMock()):
            urls = await wappalyzer_service.discover_subdomains("example.com")
        assert urls == []


class TestDiscoverAppPaths:
    @pytest.mark.asyncio
    async def test_with_http_prefix(self, wappalyzer_service):
        async def mock_check(client, url):
            return url if "/login" in url else None

        with patch.object(wappalyzer_service, "_check_url_exists", side_effect=mock_check), \
             patch("services.wappalyzer.get_shared_http_client", new_callable=AsyncMock, return_value=AsyncMock()):
            urls = await wappalyzer_service.discover_app_paths("https://example.com")
        assert "https://example.com/login" in urls

    @pytest.mark.asyncio
    async def test_without_http_prefix(self, wappalyzer_service):
        async def mock_check(client, url):
            return url if "/app" in url else None

        with patch.object(wappalyzer_service, "_check_url_exists", side_effect=mock_check), \
             patch("services.wappalyzer.get_shared_http_client", new_callable=AsyncMock, return_value=AsyncMock()):
            urls = await wappalyzer_service.discover_app_paths("example.com")
        assert any("/app" in u for u in urls)


class TestAnalyzeMultipleDomains:
    @pytest.mark.asyncio
    async def test_no_wappalyzer(self, wappalyzer_service_unavailable):
        results = await wappalyzer_service_unavailable.analyze_multiple_domains("https://example.com")
        assert results == {}

    @pytest.mark.asyncio
    async def test_with_html(self, wappalyzer_service):
        main_ts = TechStack(technologies=[DetectedTechnology(name="React", version="18", category="JS", confidence=100)], scan_url="https://example.com")

        with patch.object(wappalyzer_service, "analyze_html", new_callable=AsyncMock, return_value=main_ts), \
             patch.object(wappalyzer_service, "discover_subdomains", new_callable=AsyncMock, return_value=[]), \
             patch.object(wappalyzer_service, "discover_app_paths", new_callable=AsyncMock, return_value=[]):
            results = await wappalyzer_service.analyze_multiple_domains("https://example.com", "<html/>")
        assert "example.com" in results
        assert results["example.com"].technologies[0].name == "React"

    @pytest.mark.asyncio
    async def test_without_html(self, wappalyzer_service):
        main_ts = TechStack(technologies=[], scan_url="https://example.com")

        with patch.object(wappalyzer_service, "analyze_url", new_callable=AsyncMock, return_value=main_ts), \
             patch.object(wappalyzer_service, "discover_subdomains", new_callable=AsyncMock, return_value=[]), \
             patch.object(wappalyzer_service, "discover_app_paths", new_callable=AsyncMock, return_value=[]):
            results = await wappalyzer_service.analyze_multiple_domains("example.com")
        assert "example.com" in results
