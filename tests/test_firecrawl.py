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
    async def test_no_direct_boards_returns_none(self, firecrawl_service, client):
        async def mock_scrape(cl, url, include_html=False):
            return None

        with patch.object(firecrawl_service, "_scrape_url", side_effect=mock_scrape):
            result = await firecrawl_service._scrape_job_board(client, "Acme", "acme.com")
        assert result is None


class TestFetchSitemap:
    @pytest.mark.asyncio
    async def test_discovers_high_signal_paths(self, firecrawl_service, client):
        response = MagicMock(status_code=200)
        response.text = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/careers</loc></url>
  <url><loc>https://example.com/api/docs</loc></url>
  <url><loc>https://example.com/status</loc></url>
  <url><loc>https://example.com/platform</loc></url>
</urlset>
"""
        client.get.return_value = response

        result = await firecrawl_service._fetch_sitemap(client, "https://example.com")

        assert result == {
            "careers": "https://example.com/careers",
            "docs": "https://example.com/api/docs",
            "status": "https://example.com/status",
            "platform": "https://example.com/platform",
        }

    @pytest.mark.asyncio
    async def test_malformed_xml_returns_empty(self, firecrawl_service, client):
        response = MagicMock(status_code=200)
        response.text = "<urlset><url><loc>https://example.com/careers</loc>"
        client.get.return_value = response

        result = await firecrawl_service._fetch_sitemap(client, "https://example.com")

        assert result == {}


class TestScrapeCompany:
    @pytest.mark.asyncio
    async def test_reduced_pipeline_returns_homepage_jobs_and_site_structure(self, firecrawl_service):
        client = AsyncMock()

        with patch("services.firecrawl.get_shared_http_client", new_callable=AsyncMock, return_value=client), \
             patch.object(
                 firecrawl_service,
                 "_scrape_url",
                 new_callable=AsyncMock,
                 return_value=("# Homepage", "<html>Homepage</html>"),
             ) as mock_scrape_url, \
             patch.object(
                 firecrawl_service,
                 "_scrape_job_board",
                 new_callable=AsyncMock,
                 return_value="## Jobs from greenhouse",
             ) as mock_job_board, \
             patch.object(
                 firecrawl_service,
                 "_fetch_sitemap",
                 new_callable=AsyncMock,
                 return_value={
                     "careers": "https://example.com/careers",
                     "docs": "https://example.com/api/docs",
                 },
             ) as mock_sitemap:
            result = await firecrawl_service.scrape_company("example.com")

        mock_scrape_url.assert_awaited_once_with(client, "https://example.com", include_html=True)
        mock_job_board.assert_awaited_once_with(client, "example", "example.com")
        mock_sitemap.assert_awaited_once_with(client, "https://example.com")

        assert result.homepage == "# Homepage"
        assert result.homepage_html == "<html>Homepage</html>"
        assert result.job_postings == "## Jobs from greenhouse"
        assert result.site_structure == {
            "careers": "https://example.com/careers",
            "docs": "https://example.com/api/docs",
        }
        assert result.about is None
        assert result.blog is None
        assert result.additional_pages is None
        assert result.investor_relations is None
        assert result.web_mentions is None
