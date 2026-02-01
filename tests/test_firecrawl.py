"""Tests for services/firecrawl.py"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
import httpx
from services.firecrawl import FirecrawlService


@pytest.fixture
def firecrawl_service():
    with patch("services.firecrawl.get_settings") as m:
        m.return_value = MagicMock(firecrawl_api_key="test-key")
        return FirecrawlService()


@pytest.fixture
def client():
    return AsyncMock()


class TestScrapeUrl:
    @pytest.mark.asyncio
    async def test_success_markdown(self, firecrawl_service, client):
        resp = MagicMock(status_code=200)
        resp.json.return_value = {"data": {"markdown": "# Hello"}}
        client.post.return_value = resp
        result = await firecrawl_service._scrape_url(client, "https://x.com")
        assert result == "# Hello"

    @pytest.mark.asyncio
    async def test_success_with_html(self, firecrawl_service, client):
        resp = MagicMock(status_code=200)
        resp.json.return_value = {"data": {"markdown": "# Hi", "html": "<h1>Hi</h1>"}}
        client.post.return_value = resp
        result = await firecrawl_service._scrape_url(client, "https://x.com", include_html=True)
        assert result == ("# Hi", "<h1>Hi</h1>")

    @pytest.mark.asyncio
    async def test_http_error(self, firecrawl_service, client):
        resp = MagicMock(status_code=500)
        client.post.return_value = resp
        result = await firecrawl_service._scrape_url(client, "https://x.com")
        assert result is None

    @pytest.mark.asyncio
    async def test_http_error_with_html(self, firecrawl_service, client):
        resp = MagicMock(status_code=500)
        client.post.return_value = resp
        result = await firecrawl_service._scrape_url(client, "https://x.com", include_html=True)
        assert result == (None, None)

    @pytest.mark.asyncio
    async def test_timeout(self, firecrawl_service, client):
        client.post.side_effect = httpx.TimeoutException("t")
        result = await firecrawl_service._scrape_url(client, "https://x.com")
        assert result is None

    @pytest.mark.asyncio
    async def test_exception(self, firecrawl_service, client):
        client.post.side_effect = Exception("fail")
        result = await firecrawl_service._scrape_url(client, "https://x.com")
        assert result is None


class TestCrawlSite:
    @pytest.mark.asyncio
    async def test_success(self, firecrawl_service, client):
        post_resp = MagicMock(status_code=200)
        post_resp.json.return_value = {"id": "c1"}
        status_resp = MagicMock(status_code=200)
        status_resp.json.return_value = {"status": "completed", "data": [{"markdown": "p1"}, {"markdown": "p2"}]}
        client.post.return_value = post_resp
        client.get.return_value = status_resp

        with patch("services.firecrawl.asyncio.sleep", new_callable=AsyncMock):
            result = await firecrawl_service._crawl_site(client, "https://x.com")
        assert result == ["p1", "p2"]

    @pytest.mark.asyncio
    async def test_failed(self, firecrawl_service, client):
        post_resp = MagicMock(status_code=200)
        post_resp.json.return_value = {"id": "c1"}
        status_resp = MagicMock(status_code=200)
        status_resp.json.return_value = {"status": "failed"}
        client.post.return_value = post_resp
        client.get.return_value = status_resp

        with patch("services.firecrawl.asyncio.sleep", new_callable=AsyncMock):
            result = await firecrawl_service._crawl_site(client, "https://x.com")
        assert result == []

    @pytest.mark.asyncio
    async def test_no_crawl_id(self, firecrawl_service, client):
        post_resp = MagicMock(status_code=200)
        post_resp.json.return_value = {}
        client.post.return_value = post_resp
        result = await firecrawl_service._crawl_site(client, "https://x.com")
        assert result == []

    @pytest.mark.asyncio
    async def test_post_error(self, firecrawl_service, client):
        post_resp = MagicMock(status_code=500)
        client.post.return_value = post_resp
        result = await firecrawl_service._crawl_site(client, "https://x.com")
        assert result == []

    @pytest.mark.asyncio
    async def test_exception(self, firecrawl_service, client):
        client.post.side_effect = Exception("fail")
        result = await firecrawl_service._crawl_site(client, "https://x.com")
        assert result == []


class TestWebSearch:
    @pytest.mark.asyncio
    async def test_success(self, firecrawl_service, client):
        resp = MagicMock(status_code=200)
        resp.json.return_value = {"data": [{"title": "T", "url": "https://x.com", "markdown": "content"}]}
        client.post.return_value = resp
        result = await firecrawl_service._web_search(client, "query")
        assert "content" in result

    @pytest.mark.asyncio
    async def test_http_error(self, firecrawl_service, client):
        resp = MagicMock(status_code=500)
        client.post.return_value = resp
        result = await firecrawl_service._web_search(client, "query")
        assert result is None

    @pytest.mark.asyncio
    async def test_no_results(self, firecrawl_service, client):
        resp = MagicMock(status_code=200)
        resp.json.return_value = {"data": []}
        client.post.return_value = resp
        result = await firecrawl_service._web_search(client, "query")
        assert result is None

    @pytest.mark.asyncio
    async def test_exception(self, firecrawl_service, client):
        client.post.side_effect = Exception("fail")
        result = await firecrawl_service._web_search(client, "query")
        assert result is None


class TestScrapeJobBoard:
    @pytest.mark.asyncio
    async def test_finds_boards(self, firecrawl_service, client):
        async def mock_scrape(cl, url, include_html=False):
            if "greenhouse" in url:
                return "x" * 600  # > 500 chars
            return None

        with patch.object(firecrawl_service, "_scrape_url", side_effect=mock_scrape):
            result = await firecrawl_service._scrape_job_board(client, "Acme", "acme.com")
        assert result is not None
        assert "greenhouse" in result.lower()

    @pytest.mark.asyncio
    async def test_fallback_to_search(self, firecrawl_service, client):
        async def mock_scrape(cl, url, include_html=False):
            return None

        with patch.object(firecrawl_service, "_scrape_url", side_effect=mock_scrape), \
             patch.object(firecrawl_service, "_web_search", new_callable=AsyncMock, return_value="search results"):
            result = await firecrawl_service._scrape_job_board(client, "Acme", "acme.com")
        assert result == "search results"


class TestCheckSubdomainExists:
    @pytest.mark.asyncio
    async def test_success(self, firecrawl_service, client):
        resp = MagicMock(status_code=200, url="https://blog.example.com/page")
        client.head.return_value = resp
        result = await firecrawl_service._check_subdomain_exists(client, "https://blog.example.com")
        assert result is True

    @pytest.mark.asyncio
    async def test_redirect_different_host(self, firecrawl_service, client):
        resp = MagicMock(status_code=200, url="https://other.com")
        client.head.return_value = resp
        result = await firecrawl_service._check_subdomain_exists(client, "https://blog.example.com")
        assert result is False

    @pytest.mark.asyncio
    async def test_timeout(self, firecrawl_service, client):
        client.head.side_effect = httpx.TimeoutException("t")
        result = await firecrawl_service._check_subdomain_exists(client, "https://blog.example.com")
        assert result is False


class TestScrapeEngineeringBlog:
    @pytest.mark.asyncio
    async def test_finds_subdomain(self, firecrawl_service, client):
        async def mock_check(cl, url):
            return "engineering.example.com" in url

        with patch.object(firecrawl_service, "_check_subdomain_exists", side_effect=mock_check), \
             patch.object(firecrawl_service, "_scrape_url", new_callable=AsyncMock, return_value="x" * 400):
            result = await firecrawl_service._scrape_engineering_blog(client, "example.com")
        assert result is not None

    @pytest.mark.asyncio
    async def test_none_found(self, firecrawl_service, client):
        async def mock_check(cl, url):
            return False

        with patch.object(firecrawl_service, "_check_subdomain_exists", side_effect=mock_check):
            result = await firecrawl_service._scrape_engineering_blog(client, "example.com")
        assert result is None


class TestScrapeDeveloperDocs:
    @pytest.mark.asyncio
    async def test_finds_subdomain(self, firecrawl_service, client):
        async def mock_check(cl, url):
            return "docs.example.com" in url

        with patch.object(firecrawl_service, "_check_subdomain_exists", side_effect=mock_check), \
             patch.object(firecrawl_service, "_scrape_url", new_callable=AsyncMock, return_value="x" * 400):
            result = await firecrawl_service._scrape_developer_docs(client, "example.com")
        assert result is not None
        assert "Developer Documentation" in result

    @pytest.mark.asyncio
    async def test_none_found(self, firecrawl_service, client):
        async def mock_check(cl, url):
            return False

        with patch.object(firecrawl_service, "_check_subdomain_exists", side_effect=mock_check):
            result = await firecrawl_service._scrape_developer_docs(client, "example.com")
        assert result is None


class TestScrapeInvestorRelations:
    @pytest.mark.asyncio
    async def test_finds_subdomain(self, firecrawl_service, client):
        async def mock_check(cl, url):
            return "investor.example.com" in url

        async def mock_scrape(cl, url, include_html=False):
            return "x" * 400

        with patch.object(firecrawl_service, "_check_subdomain_exists", side_effect=mock_check), \
             patch.object(firecrawl_service, "_scrape_url", side_effect=mock_scrape):
            result = await firecrawl_service._scrape_investor_relations(client, "example.com")
        assert result is not None

    @pytest.mark.asyncio
    async def test_none_found(self, firecrawl_service, client):
        async def mock_check(cl, url):
            return False

        with patch.object(firecrawl_service, "_check_subdomain_exists", side_effect=mock_check):
            result = await firecrawl_service._scrape_investor_relations(client, "example.com")
        assert result is None
