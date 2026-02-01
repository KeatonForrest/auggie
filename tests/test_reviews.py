"""Tests for services/reviews.py - G2 and Capterra review scraping."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

from services.reviews import ReviewsService


@pytest.fixture
def mock_settings():
    """Mock settings with Firecrawl API key."""
    settings = MagicMock()
    settings.firecrawl_api_key = "test-api-key"
    return settings


@pytest.fixture
def reviews_service(mock_settings):
    """Create ReviewsService with mocked settings."""
    with patch("services.reviews.get_settings", return_value=mock_settings):
        service = ReviewsService()
    return service


class TestCleanName:
    """Tests for _clean_name method."""

    def test_strips_dotcom(self, reviews_service):
        assert reviews_service._clean_name("example.com") == "example"

    def test_strips_dotio(self, reviews_service):
        assert reviews_service._clean_name("example.io") == "example"

    def test_strips_dotai(self, reviews_service):
        assert reviews_service._clean_name("example.ai") == "example"

    def test_strips_hq_suffix(self, reviews_service):
        assert reviews_service._clean_name("examplehq") == "example"

    def test_strips_app_suffix(self, reviews_service):
        assert reviews_service._clean_name("exampleapp") == "example"

    def test_strips_inc_suffix(self, reviews_service):
        assert reviews_service._clean_name("exampleinc") == "example"

    def test_strips_corp_suffix(self, reviews_service):
        assert reviews_service._clean_name("examplecorp") == "example"

    def test_no_suffix_unchanged(self, reviews_service):
        assert reviews_service._clean_name("example") == "example"

    def test_strips_whitespace(self, reviews_service):
        # Whitespace is stripped at end, but suffix check happens before strip
        assert reviews_service._clean_name("  example  ") == "example"

    def test_only_strips_one_suffix(self, reviews_service):
        # Should strip .com but not .co
        assert reviews_service._clean_name("example.com") == "example"

    def test_short_name_not_stripped(self, reviews_service):
        # Should not strip suffix if it would leave too short a name
        assert reviews_service._clean_name("hq") == "hq"


class TestExtractG2Content:
    """Tests for _extract_g2_content method."""

    def test_truncates_at_6000_chars(self, reviews_service):
        markdown = "a" * 10000
        url = "https://www.g2.com/products/test/reviews"
        result = reviews_service._extract_g2_content(markdown, url)

        # Should include "Source: {url}\n" + 6000 chars
        assert result.startswith(f"Source: {url}\n")
        content = result[len(f"Source: {url}\n"):]
        assert len(content) == 6000

    def test_includes_source_url(self, reviews_service):
        markdown = "test content"
        url = "https://www.g2.com/products/test/reviews"
        result = reviews_service._extract_g2_content(markdown, url)

        assert result.startswith(f"Source: {url}\n")

    def test_preserves_short_content(self, reviews_service):
        markdown = "short content"
        url = "https://www.g2.com/products/test/reviews"
        result = reviews_service._extract_g2_content(markdown, url)

        assert f"Source: {url}\nshort content" == result


class TestExtractCapterraContent:
    """Tests for _extract_capterra_content method."""

    def test_truncates_at_4000_chars(self, reviews_service):
        markdown = "b" * 8000
        url = "https://www.capterra.com/p/test/reviews/"
        result = reviews_service._extract_capterra_content(markdown, url)

        # Should include "Source: {url}\n" + 4000 chars
        assert result.startswith(f"Source: {url}\n")
        content = result[len(f"Source: {url}\n"):]
        assert len(content) == 4000

    def test_includes_source_url(self, reviews_service):
        markdown = "test content"
        url = "https://www.capterra.com/p/test/reviews/"
        result = reviews_service._extract_capterra_content(markdown, url)

        assert result.startswith(f"Source: {url}\n")

    def test_preserves_short_content(self, reviews_service):
        markdown = "short capterra content"
        url = "https://www.capterra.com/p/test/reviews/"
        result = reviews_service._extract_capterra_content(markdown, url)

        assert f"Source: {url}\nshort capterra content" == result


class TestGetReviews:
    """Tests for get_reviews method."""

    @pytest.mark.asyncio
    async def test_both_g2_and_capterra_results(self, reviews_service):
        """Should combine both G2 and Capterra results."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)

        with patch.object(reviews_service, "_get_reviews_impl", new=AsyncMock()) as mock_impl:
            mock_impl.return_value = "### G2 Reviews\nG2 content\n\n### Capterra Reviews\nCapterra content\n\n"

            result = await reviews_service.get_reviews("TestCompany", client=mock_client)

            assert "### G2 Reviews" in result
            assert "### Capterra Reviews" in result
            mock_impl.assert_called_once_with(mock_client, "TestCompany")

    @pytest.mark.asyncio
    async def test_only_g2_results(self, reviews_service):
        """Should return only G2 section when Capterra fails."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)

        with patch.object(reviews_service, "_scrape_g2", new=AsyncMock(return_value="G2 content")):
            with patch.object(reviews_service, "_scrape_capterra", new=AsyncMock(return_value=None)):
                result = await reviews_service.get_reviews("TestCompany", client=mock_client)

                assert "### G2 Reviews" in result
                assert "G2 content" in result
                assert "### Capterra Reviews" not in result

    @pytest.mark.asyncio
    async def test_only_capterra_results(self, reviews_service):
        """Should return only Capterra section when G2 fails."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)

        with patch.object(reviews_service, "_scrape_g2", new=AsyncMock(return_value=None)):
            with patch.object(reviews_service, "_scrape_capterra", new=AsyncMock(return_value="Capterra content")):
                result = await reviews_service.get_reviews("TestCompany", client=mock_client)

                assert "### Capterra Reviews" in result
                assert "Capterra content" in result
                assert "### G2 Reviews" not in result

    @pytest.mark.asyncio
    async def test_neither_source_returns_none(self, reviews_service):
        """Should return None when both sources fail."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)

        with patch.object(reviews_service, "_scrape_g2", new=AsyncMock(return_value=None)):
            with patch.object(reviews_service, "_scrape_capterra", new=AsyncMock(return_value=None)):
                result = await reviews_service.get_reviews("TestCompany", client=mock_client)

                assert result is None

    @pytest.mark.asyncio
    async def test_creates_own_client_when_none_provided(self, reviews_service):
        """Should create its own httpx client when none provided."""
        with patch.object(reviews_service, "_scrape_g2", new=AsyncMock(return_value="G2 content")):
            with patch.object(reviews_service, "_scrape_capterra", new=AsyncMock(return_value=None)):
                result = await reviews_service.get_reviews("TestCompany", client=None)

                assert result is not None
                assert "### G2 Reviews" in result

    @pytest.mark.asyncio
    async def test_uses_provided_client(self, reviews_service):
        """Should use provided client instead of creating new one."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)

        with patch.object(reviews_service, "_get_reviews_impl", new=AsyncMock(return_value="result")) as mock_impl:
            await reviews_service.get_reviews("TestCompany", client=mock_client)

            # Should call impl with provided client
            mock_impl.assert_called_once_with(mock_client, "TestCompany")

    @pytest.mark.asyncio
    async def test_exception_returns_none(self, reviews_service):
        """Should catch exceptions and return None."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)

        with patch.object(reviews_service, "_get_reviews_impl", new=AsyncMock(side_effect=Exception("Test error"))):
            result = await reviews_service.get_reviews("TestCompany", client=mock_client)

            assert result is None


class TestScrapeG2:
    """Tests for _scrape_g2 method."""

    @pytest.mark.asyncio
    async def test_direct_hit_success(self, reviews_service):
        """Should return content on direct URL hit."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "markdown": "a" * 300  # Long enough to pass the check
            }
        }
        mock_client.post.return_value = mock_response

        result = await reviews_service._scrape_g2(mock_client, "TestCompany")

        assert result is not None
        assert "Source: https://www.g2.com/products/testcompany/reviews" in result
        # Should only call direct scrape, not search
        assert mock_client.post.call_count == 1

    @pytest.mark.asyncio
    async def test_direct_miss_search_fallback_success(self, reviews_service):
        """Should fall back to search when direct URL fails."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)

        # First call (direct scrape) returns empty markdown
        direct_response = MagicMock()
        direct_response.status_code = 200
        direct_response.json.return_value = {"data": {"markdown": "short"}}  # Too short

        # Second call (search) returns results
        search_response = MagicMock()
        search_response.status_code = 200
        search_response.json.return_value = {
            "data": [
                {
                    "url": "https://www.g2.com/products/testcompany/reviews",
                    "markdown": "search result content"
                }
            ]
        }

        mock_client.post.side_effect = [direct_response, search_response]

        result = await reviews_service._scrape_g2(mock_client, "TestCompany")

        assert result is not None
        assert "search result content" in result
        assert mock_client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_search_with_products_url_match(self, reviews_service):
        """Should prefer g2.com/products/ URLs in search results."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)

        # Direct scrape fails
        direct_response = MagicMock()
        direct_response.status_code = 404

        # Search returns multiple results
        search_response = MagicMock()
        search_response.status_code = 200
        search_response.json.return_value = {
            "data": [
                {
                    "url": "https://www.g2.com/other-page",
                    "markdown": "other content"
                },
                {
                    "url": "https://www.g2.com/products/testcompany/reviews",
                    "markdown": "product page content"
                }
            ]
        }

        mock_client.post.side_effect = [direct_response, search_response]

        result = await reviews_service._scrape_g2(mock_client, "TestCompany")

        assert result is not None
        assert "product page content" in result

    @pytest.mark.asyncio
    async def test_search_with_generic_g2_match(self, reviews_service):
        """Should accept any g2.com URL if no products/ URL found."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)

        # Direct scrape fails
        direct_response = MagicMock()
        direct_response.status_code = 404

        # Search returns only generic g2.com URL
        search_response = MagicMock()
        search_response.status_code = 200
        search_response.json.return_value = {
            "data": [
                {
                    "url": "https://www.g2.com/categories/test",
                    "markdown": "category content"
                }
            ]
        }

        mock_client.post.side_effect = [direct_response, search_response]

        result = await reviews_service._scrape_g2(mock_client, "TestCompany")

        assert result is not None
        assert "category content" in result

    @pytest.mark.asyncio
    async def test_search_returns_no_results(self, reviews_service):
        """Should return None when search finds nothing."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)

        # Direct scrape fails
        direct_response = MagicMock()
        direct_response.status_code = 404

        # Search returns empty results
        search_response = MagicMock()
        search_response.status_code = 200
        search_response.json.return_value = {"data": []}

        mock_client.post.side_effect = [direct_response, search_response]

        result = await reviews_service._scrape_g2(mock_client, "TestCompany")

        assert result is None

    @pytest.mark.asyncio
    async def test_search_http_error(self, reviews_service):
        """Should return None when search returns HTTP error."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)

        # Direct scrape fails
        direct_response = MagicMock()
        direct_response.status_code = 404

        # Search returns error
        search_response = MagicMock()
        search_response.status_code = 500

        mock_client.post.side_effect = [direct_response, search_response]

        result = await reviews_service._scrape_g2(mock_client, "TestCompany")

        assert result is None

    @pytest.mark.asyncio
    async def test_search_exception(self, reviews_service):
        """Should return None when search raises exception."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)

        # Direct scrape fails
        direct_response = MagicMock()
        direct_response.status_code = 404

        # Search raises exception
        mock_client.post.side_effect = [direct_response, Exception("Network error")]

        result = await reviews_service._scrape_g2(mock_client, "TestCompany")

        assert result is None


class TestScrapeCapterra:
    """Tests for _scrape_capterra method."""

    @pytest.mark.asyncio
    async def test_direct_hit_success(self, reviews_service):
        """Should return content on direct URL hit."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "markdown": "x" * 300  # Long enough to pass the check
            }
        }
        mock_client.post.return_value = mock_response

        result = await reviews_service._scrape_capterra(mock_client, "TestCompany")

        assert result is not None
        assert "Source: https://www.capterra.com/p/testcompany/reviews/" in result
        # Should only call direct scrape, not search
        assert mock_client.post.call_count == 1

    @pytest.mark.asyncio
    async def test_search_fallback_success(self, reviews_service):
        """Should fall back to search when direct URL fails."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)

        # First call (direct scrape) returns empty markdown
        direct_response = MagicMock()
        direct_response.status_code = 200
        direct_response.json.return_value = {"data": {"markdown": "short"}}  # Too short

        # Second call (search) returns results
        search_response = MagicMock()
        search_response.status_code = 200
        search_response.json.return_value = {
            "data": [
                {
                    "url": "https://www.capterra.com/p/testcompany/reviews/",
                    "markdown": "capterra search result"
                }
            ]
        }

        mock_client.post.side_effect = [direct_response, search_response]

        result = await reviews_service._scrape_capterra(mock_client, "TestCompany")

        assert result is not None
        assert "capterra search result" in result
        assert mock_client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_search_returns_no_results(self, reviews_service):
        """Should return None when search finds nothing."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)

        # Direct scrape fails
        direct_response = MagicMock()
        direct_response.status_code = 404

        # Search returns empty results
        search_response = MagicMock()
        search_response.status_code = 200
        search_response.json.return_value = {"data": []}

        mock_client.post.side_effect = [direct_response, search_response]

        result = await reviews_service._scrape_capterra(mock_client, "TestCompany")

        assert result is None

    @pytest.mark.asyncio
    async def test_search_http_error(self, reviews_service):
        """Should return None when search returns HTTP error."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)

        # Direct scrape fails
        direct_response = MagicMock()
        direct_response.status_code = 404

        # Search returns error
        search_response = MagicMock()
        search_response.status_code = 503

        mock_client.post.side_effect = [direct_response, search_response]

        result = await reviews_service._scrape_capterra(mock_client, "TestCompany")

        assert result is None

    @pytest.mark.asyncio
    async def test_direct_exception_then_search(self, reviews_service):
        """Should fall back to search when direct scrape raises exception."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)

        # Search returns results
        search_response = MagicMock()
        search_response.status_code = 200
        search_response.json.return_value = {
            "data": [
                {
                    "url": "https://www.capterra.com/software/123/test",
                    "markdown": "found via search"
                }
            ]
        }

        # Direct scrape raises exception, then search succeeds
        mock_client.post.side_effect = [Exception("Timeout"), search_response]

        result = await reviews_service._scrape_capterra(mock_client, "TestCompany")

        assert result is not None
        assert "found via search" in result


class TestReviewsServiceInit:
    """Tests for ReviewsService initialization."""

    def test_init_sets_firecrawl_url(self, mock_settings):
        """Should set Firecrawl API URL."""
        with patch("services.reviews.get_settings", return_value=mock_settings):
            service = ReviewsService()
            assert service.firecrawl_url == "https://api.firecrawl.dev/v1"

    def test_init_sets_headers_with_bearer_token(self, mock_settings):
        """Should set Authorization header with Bearer token."""
        with patch("services.reviews.get_settings", return_value=mock_settings):
            service = ReviewsService()
            assert service.headers["Authorization"] == "Bearer test-api-key"
            assert service.headers["Content-Type"] == "application/json"

    def test_init_gets_settings(self, mock_settings):
        """Should call get_settings on initialization."""
        with patch("services.reviews.get_settings", return_value=mock_settings) as mock_get:
            service = ReviewsService()
            mock_get.assert_called_once()
            assert service.settings == mock_settings
