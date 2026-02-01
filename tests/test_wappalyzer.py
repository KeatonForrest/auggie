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
         patch("services.wappalyzer.TechDetector") as mock_cls:
        mock_cls.return_value = mock_wappalyzer
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
    def test_success_with_headers(self, wappalyzer_service):
        """When headers are provided, no extra fetch occurs."""
        with patch("services.wappalyzer.WebPage") as mock_wp:
            mock_wp.return_value = MagicMock()
            wappalyzer_service.wappalyzer.analyze_with_versions_and_categories.return_value = {
                "Bootstrap": {"versions": ["5"], "categories": ["UI"]}
            }
            ts = wappalyzer_service._sync_analyze_html("<html/>", "https://x.com", {"Server": "nginx"})
        assert len(ts.technologies) == 1
        mock_wp.assert_called_once_with("https://x.com", "<html/>", {"Server": "nginx"})

    def test_exception_returns_empty(self, wappalyzer_service):
        with patch("services.wappalyzer.WebPage") as mock_wp:
            mock_wp.side_effect = Exception("fail")
            ts = wappalyzer_service._sync_analyze_html("<html/>", "https://x.com", {})
        assert len(ts.technologies) == 0


class TestAnalyzeHtmlAsyncHeaderFetch:
    @pytest.mark.asyncio
    async def test_fetches_headers_async_when_empty(self, wappalyzer_service):
        """When headers are not provided, analyze_html fetches them via async httpx."""
        mock_headers = {"Server": "nginx", "X-Powered-By": "PHP/8.1"}
        with patch.object(wappalyzer_service, "_fetch_headers", new_callable=AsyncMock, return_value=mock_headers), \
             patch("services.wappalyzer.WebPage") as mock_wp:
            mock_wp.return_value = MagicMock()
            wappalyzer_service.wappalyzer.analyze_with_versions_and_categories.return_value = {}
            await wappalyzer_service.analyze_html("<html/>", "https://x.com")
            wappalyzer_service._fetch_headers.assert_awaited_once_with("https://x.com")

    @pytest.mark.asyncio
    async def test_skips_fetch_when_headers_provided(self, wappalyzer_service):
        """When headers are provided, _fetch_headers is not called."""
        with patch.object(wappalyzer_service, "_fetch_headers", new_callable=AsyncMock) as mock_fetch, \
             patch("services.wappalyzer.WebPage") as mock_wp:
            mock_wp.return_value = MagicMock()
            wappalyzer_service.wappalyzer.analyze_with_versions_and_categories.return_value = {}
            await wappalyzer_service.analyze_html("<html/>", "https://x.com", {"Server": "nginx"})
            mock_fetch.assert_not_awaited()


class TestFetchHeaders:
    @pytest.mark.asyncio
    async def test_returns_headers(self, wappalyzer_service):
        mock_resp = MagicMock()
        mock_resp.headers = {"Server": "nginx"}
        mock_client = AsyncMock()
        mock_client.head.return_value = mock_resp
        with patch("services.wappalyzer.get_shared_http_client", new_callable=AsyncMock, return_value=mock_client):
            result = await wappalyzer_service._fetch_headers("https://x.com")
        assert result == {"Server": "nginx"}

    @pytest.mark.asyncio
    async def test_returns_empty_on_error(self, wappalyzer_service):
        mock_client = AsyncMock()
        mock_client.head.side_effect = Exception("fail")
        with patch("services.wappalyzer.get_shared_http_client", new_callable=AsyncMock, return_value=mock_client):
            result = await wappalyzer_service._fetch_headers("https://x.com")
        assert result == {}


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
    async def test_head_success_returns_tuple(self, wappalyzer_service):
        client = AsyncMock()
        resp = MagicMock(status_code=200, url="https://example.com/app", headers={"Server": "nginx"})
        client.head.return_value = resp
        result = await wappalyzer_service._check_url_exists(client, "https://example.com/app")
        assert result == ("https://example.com/app", {"Server": "nginx"})

    @pytest.mark.asyncio
    async def test_head_404_returns_none(self, wappalyzer_service):
        client = AsyncMock()
        resp = MagicMock(status_code=404)
        client.head.return_value = resp
        result = await wappalyzer_service._check_url_exists(client, "https://example.com/app")
        assert result is None

    @pytest.mark.asyncio
    async def test_head_403_returns_none(self, wappalyzer_service):
        """403 is now rejected — no hostile recon of forbidden resources."""
        client = AsyncMock()
        resp = MagicMock(status_code=403, url="https://example.com/app")
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
        resp = MagicMock(status_code=200, url="https://example.com/app", headers={"Server": "nginx"})
        client.get.return_value = resp
        result = await wappalyzer_service._check_url_exists(client, "https://example.com/app")
        assert result == ("https://example.com/app", {"Server": "nginx"})

    @pytest.mark.asyncio
    async def test_both_fail(self, wappalyzer_service):
        client = AsyncMock()
        client.head.side_effect = Exception("e")
        client.get.side_effect = Exception("fail")
        result = await wappalyzer_service._check_url_exists(client, "https://example.com/app")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_fallback_400_returns_none(self, wappalyzer_service):
        """GET fallback also rejects >= 400."""
        client = AsyncMock()
        client.head.side_effect = Exception("unknown")
        resp = MagicMock(status_code=403, url="https://example.com/app")
        client.get.return_value = resp
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


class TestRobotsFiltering:
    @pytest.mark.asyncio
    async def test_disallowed_paths_skipped(self, wappalyzer_service):
        """Paths disallowed by robots.txt are not probed."""
        from urllib.robotparser import RobotFileParser
        rp = RobotFileParser()
        rp.parse([
            "User-agent: *",
            "Disallow: /admin",
            "Disallow: /login",
        ])

        async def mock_check(client, url):
            # Everything that gets checked is "found"
            return (url, {"Server": "nginx"})

        with patch.object(wappalyzer_service, "_fetch_robots", new_callable=AsyncMock, return_value=rp), \
             patch.object(wappalyzer_service, "_rate_limited_check", side_effect=mock_check), \
             patch("services.wappalyzer.get_shared_http_client", new_callable=AsyncMock, return_value=AsyncMock()):
            found = await wappalyzer_service.discover_app_paths("https://example.com")

        found_urls = [u for u, _ in found]
        # /login is in COMMON_APP_PATHS but disallowed by robots.txt
        assert not any("/login" in u for u in found_urls)
        # /app is allowed and should be present
        assert any("/app" in u for u in found_urls)

    @pytest.mark.asyncio
    async def test_no_robots_checks_all_paths(self, wappalyzer_service):
        """When robots.txt is unavailable, all paths are checked."""
        async def mock_check(client, url):
            return (url, {})

        with patch.object(wappalyzer_service, "_fetch_robots", new_callable=AsyncMock, return_value=None), \
             patch.object(wappalyzer_service, "_rate_limited_check", side_effect=mock_check), \
             patch("services.wappalyzer.get_shared_http_client", new_callable=AsyncMock, return_value=AsyncMock()):
            found = await wappalyzer_service.discover_app_paths("https://example.com")

        assert len(found) == len(wappalyzer_service.COMMON_APP_PATHS)


class TestDiscoverSubdomains:
    @pytest.mark.asyncio
    async def test_finds_some(self, wappalyzer_service):
        async def mock_check(client, url):
            return (url, {"Server": "nginx"}) if "app.example.com" in url else None

        with patch.object(wappalyzer_service, "_rate_limited_check", side_effect=mock_check), \
             patch("services.wappalyzer.get_shared_http_client", new_callable=AsyncMock, return_value=AsyncMock()):
            results = await wappalyzer_service.discover_subdomains("https://www.example.com")
        urls = [u for u, _ in results]
        assert "https://app.example.com" in urls

    @pytest.mark.asyncio
    async def test_finds_none(self, wappalyzer_service):
        async def mock_check(client, url):
            return None

        with patch.object(wappalyzer_service, "_rate_limited_check", side_effect=mock_check), \
             patch("services.wappalyzer.get_shared_http_client", new_callable=AsyncMock, return_value=AsyncMock()):
            results = await wappalyzer_service.discover_subdomains("example.com")
        assert results == []


class TestDiscoverAppPaths:
    @pytest.mark.asyncio
    async def test_with_http_prefix(self, wappalyzer_service):
        async def mock_check(client, url):
            return (url, {}) if "/login" in url else None

        with patch.object(wappalyzer_service, "_rate_limited_check", side_effect=mock_check), \
             patch.object(wappalyzer_service, "_fetch_robots", new_callable=AsyncMock, return_value=None), \
             patch("services.wappalyzer.get_shared_http_client", new_callable=AsyncMock, return_value=AsyncMock()):
            results = await wappalyzer_service.discover_app_paths("https://example.com")
        urls = [u for u, _ in results]
        assert "https://example.com/login" in urls

    @pytest.mark.asyncio
    async def test_without_http_prefix(self, wappalyzer_service):
        async def mock_check(client, url):
            return (url, {}) if "/app" in url else None

        with patch.object(wappalyzer_service, "_rate_limited_check", side_effect=mock_check), \
             patch.object(wappalyzer_service, "_fetch_robots", new_callable=AsyncMock, return_value=None), \
             patch("services.wappalyzer.get_shared_http_client", new_callable=AsyncMock, return_value=AsyncMock()):
            results = await wappalyzer_service.discover_app_paths("example.com")
        urls = [u for u, _ in results]
        assert any("/app" in u for u in urls)


class TestScoreSecurityHeaders:
    def test_all_present(self):
        from services.wappalyzer import WappalyzerService
        headers = {
            "Strict-Transport-Security": "max-age=31536000",
            "Content-Security-Policy": "default-src 'self'",
            "X-Frame-Options": "DENY",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "Permissions-Policy": "camera=()",
        }
        result = WappalyzerService.score_security_headers(headers)
        assert result.score == 6
        assert result.grade == "A"
        assert len(result.missing) == 0

    def test_none_present(self):
        from services.wappalyzer import WappalyzerService
        result = WappalyzerService.score_security_headers({})
        assert result.score == 0
        assert result.grade == "F"
        assert len(result.present) == 0

    def test_partial(self):
        from services.wappalyzer import WappalyzerService
        headers = {
            "Strict-Transport-Security": "max-age=31536000",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
        }
        result = WappalyzerService.score_security_headers(headers)
        assert result.score == 3
        assert result.grade == "C"

    def test_case_insensitive(self):
        from services.wappalyzer import WappalyzerService
        headers = {"strict-transport-security": "max-age=31536000"}
        result = WappalyzerService.score_security_headers(headers)
        assert result.score == 1


class TestExtractRobotsSignals:
    def test_api_and_admin_paths(self):
        from services.wappalyzer import WappalyzerService
        text = "User-agent: *\nDisallow: /api/v1\nDisallow: /admin\nDisallow: /private\n"
        result = WappalyzerService.extract_robots_signals(text)
        assert "/api/v1" in result.api_paths
        assert "/admin" in result.admin_paths
        assert len(result.interesting_disallows) == 3

    def test_crawl_delay(self):
        from services.wappalyzer import WappalyzerService
        text = "User-agent: *\nCrawl-delay: 10\nDisallow: /search\n"
        result = WappalyzerService.extract_robots_signals(text)
        assert result.crawl_delay == 10.0

    def test_graphql_path(self):
        from services.wappalyzer import WappalyzerService
        text = "User-agent: *\nDisallow: /graphql\n"
        result = WappalyzerService.extract_robots_signals(text)
        assert "/graphql" in result.api_paths

    def test_empty(self):
        from services.wappalyzer import WappalyzerService
        result = WappalyzerService.extract_robots_signals("")
        assert result.api_paths == []
        assert result.crawl_delay is None


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

    @pytest.mark.asyncio
    async def test_subdomains_use_probe_headers(self, wappalyzer_service):
        """analyze_multiple_domains uses analyze_html with probe headers, not analyze_url."""
        main_ts = TechStack(technologies=[], scan_url="https://example.com")
        sub_ts = TechStack(
            technologies=[DetectedTechnology(name="Express", version="4", category="Web", confidence=100)],
            scan_url="https://app.example.com"
        )

        with patch.object(wappalyzer_service, "analyze_url", new_callable=AsyncMock, return_value=main_ts) as mock_url, \
             patch.object(wappalyzer_service, "analyze_html", new_callable=AsyncMock, return_value=sub_ts) as mock_html, \
             patch.object(wappalyzer_service, "discover_subdomains", new_callable=AsyncMock,
                          return_value=[("https://app.example.com", {"Server": "nginx"})]), \
             patch.object(wappalyzer_service, "discover_app_paths", new_callable=AsyncMock, return_value=[]):
            results = await wappalyzer_service.analyze_multiple_domains("example.com")

        # analyze_html should be called for the subdomain with probe headers
        mock_html.assert_any_call("", "https://app.example.com", {"Server": "nginx"})
        assert "app.example.com" in results


class TestConfidencePassthrough:
    def test_confidence_passthrough(self, wappalyzer_service):
        """DetectedTechnology.confidence matches detector output, not hardcoded 100."""
        results = {
            "React": {"versions": ["18"], "categories": ["JS"], "confidence": 72},
            "Nginx": {"versions": [], "categories": ["Web servers"], "confidence": 50},
        }
        ts = wappalyzer_service._parse_technologies(results, "https://example.com")
        by_name = {t.name: t for t in ts.technologies}
        assert by_name["React"].confidence == 72
        assert by_name["Nginx"].confidence == 50

    def test_confidence_defaults_to_100(self, wappalyzer_service):
        """When confidence key is missing, defaults to 100."""
        results = {"React": {"versions": [], "categories": ["JS"]}}
        ts = wappalyzer_service._parse_technologies(results, "https://example.com")
        assert ts.technologies[0].confidence == 100
