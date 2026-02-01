"""Tests for services/news.py - NewsService for fetching company news via SerpAPI."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
import httpx

from services.news import NewsService


@pytest.fixture
def mock_settings():
    """Mock settings with API key."""
    settings = MagicMock()
    settings.serp_api_key = "test_api_key"
    return settings


@pytest.fixture
def mock_settings_no_key():
    """Mock settings without API key."""
    settings = MagicMock()
    settings.serp_api_key = None
    return settings


@pytest.fixture
def news_service(mock_settings):
    """Create NewsService instance with mocked settings."""
    with patch("services.news.get_settings", return_value=mock_settings):
        service = NewsService()
    return service


@pytest.fixture
def news_service_no_key(mock_settings_no_key):
    """Create NewsService instance without API key."""
    with patch("services.news.get_settings", return_value=mock_settings_no_key):
        service = NewsService()
    return service


class TestCleanCompanyName:
    """Tests for _clean_company_name method."""

    def test_strips_inc_with_comma(self, news_service):
        result = news_service._clean_company_name("Acme, Inc.")
        assert result == "Acme"

    def test_strips_corp(self, news_service):
        result = news_service._clean_company_name("Acme Corp.")
        assert result == "Acme"

    def test_strips_dotcom(self, news_service):
        result = news_service._clean_company_name("Acme.com")
        assert result == "Acme"

    def test_strips_llc(self, news_service):
        """Test stripping ' LLC' suffix."""
        result = news_service._clean_company_name("Acme Company LLC")
        assert result == "Acme Company"

    def test_strips_dotcom(self, news_service):
        """Test stripping '.com' suffix."""
        result = news_service._clean_company_name("acme.com")
        assert result == "acme"

    def test_strips_dotai(self, news_service):
        """Test stripping '.ai' suffix."""
        result = news_service._clean_company_name("acme.ai")
        assert result == "acme"

    def test_no_suffix(self, news_service):
        """Test company name without suffix remains unchanged."""
        result = news_service._clean_company_name("Acme Company")
        assert result == "Acme Company"


class TestFormatArticles:
    """Tests for _format_articles method."""

    def test_multiple_articles(self, news_service):
        """Test formatting multiple articles with all fields."""
        articles = [
            {
                "title": "First Article",
                "source": {"name": "News Source 1"},
                "date": "2024-01-01",
                "snippet": "First article snippet",
                "link": "https://example.com/1"
            },
            {
                "title": "Second Article",
                "source": {"name": "News Source 2"},
                "date": "2024-01-02",
                "snippet": "Second article snippet",
                "link": "https://example.com/2"
            }
        ]

        result = news_service._format_articles(articles)

        assert "**First Article**" in result
        assert "Source: News Source 1 | 2024-01-01" in result
        assert "First article snippet" in result
        assert "Link: https://example.com/1" in result
        assert "**Second Article**" in result
        assert "Source: News Source 2 | 2024-01-02" in result
        assert "Second article snippet" in result
        assert "Link: https://example.com/2" in result

    def test_article_without_title_skipped(self, news_service):
        """Test that articles without title are skipped."""
        articles = [
            {
                "title": "Valid Article",
                "source": {"name": "News Source"},
                "date": "2024-01-01",
                "snippet": "Valid snippet",
                "link": "https://example.com/1"
            },
            {
                "source": {"name": "News Source 2"},
                "date": "2024-01-02",
                "snippet": "No title snippet",
                "link": "https://example.com/2"
            }
        ]

        result = news_service._format_articles(articles)

        assert "**Valid Article**" in result
        assert "No title snippet" not in result
        assert "https://example.com/2" not in result

    def test_returns_none_for_empty(self, news_service):
        """Test that empty article list returns None."""
        result = news_service._format_articles([])
        assert result is None

    def test_article_with_missing_fields(self, news_service):
        """Test formatting article with missing optional fields."""
        articles = [
            {
                "title": "Article Title",
                "source": {},
                "date": "",
            }
        ]

        result = news_service._format_articles(articles)

        assert "**Article Title**" in result
        assert "Source: Unknown" in result

    def test_article_without_snippet(self, news_service):
        """Test formatting article without snippet."""
        articles = [
            {
                "title": "Article Title",
                "source": {"name": "News Source"},
                "date": "2024-01-01",
                "link": "https://example.com/1"
            }
        ]

        result = news_service._format_articles(articles)

        assert "**Article Title**" in result
        assert "Source: News Source | 2024-01-01" in result
        assert "Link: https://example.com/1" in result


class TestGetCompanyNews:
    """Tests for get_company_news method."""

    @pytest.mark.asyncio
    async def test_success(self, news_service):
        """Test successful news fetching."""
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "news_results": [
                {
                    "title": "Test Article",
                    "source": {"name": "Test Source"},
                    "date": "2024-01-01",
                    "snippet": "Test snippet",
                    "link": "https://example.com/test"
                }
            ]
        }
        mock_client.get.return_value = mock_response

        result = await news_service.get_company_news("Acme Inc.", client=mock_client)

        assert result is not None
        assert "**Test Article**" in result
        assert "Test Source" in result
        mock_client.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_api_key_returns_none(self, news_service_no_key):
        """Test that missing API key returns None."""
        result = await news_service_no_key.get_company_news("Acme Inc.")
        assert result is None

    @pytest.mark.asyncio
    async def test_exception_returns_none(self, news_service):
        """Test that exceptions are caught and None is returned."""
        mock_client = AsyncMock()
        mock_client.get.side_effect = Exception("Network error")

        result = await news_service.get_company_news("Acme Inc.", client=mock_client)

        assert result is None

    @pytest.mark.asyncio
    async def test_with_provided_client(self, news_service):
        """Test using provided client instead of creating new one."""
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "news_results": [
                {
                    "title": "Test Article",
                    "source": {"name": "Test Source"},
                    "date": "2024-01-01",
                    "snippet": "Test snippet",
                    "link": "https://example.com/test"
                }
            ]
        }
        mock_client.get.return_value = mock_response

        result = await news_service.get_company_news("Acme Inc.", client=mock_client)

        assert result is not None
        mock_client.get.assert_called_once()

    @pytest.mark.asyncio
    @patch("services.news.httpx.AsyncClient")
    async def test_creates_client_when_none_provided(self, mock_async_client_class, news_service):
        """Test that client is created when None is provided."""
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "news_results": [
                {
                    "title": "Test Article",
                    "source": {"name": "Test Source"},
                    "date": "2024-01-01",
                    "snippet": "Test snippet",
                    "link": "https://example.com/test"
                }
            ]
        }
        mock_client.get.return_value = mock_response
        mock_async_client_class.return_value.__aenter__.return_value = mock_client

        result = await news_service.get_company_news("Acme Inc.")

        assert result is not None
        mock_client.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleans_company_name(self, news_service):
        """Test that company name is cleaned before search."""
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"news_results": []}
        mock_client.get.return_value = mock_response

        await news_service.get_company_news("Acme, Inc.", client=mock_client)

        call_args = mock_client.get.call_args
        params = call_args.kwargs["params"]
        assert params["q"] == "Acme"


class TestFetchNews:
    """Tests for _fetch_news method."""

    @pytest.mark.asyncio
    async def test_success(self, news_service):
        """Test successful news fetch."""
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "news_results": [
                {
                    "title": "Test Article",
                    "source": {"name": "Test Source"},
                    "date": "2024-01-01",
                    "snippet": "Test snippet",
                    "link": "https://example.com/test"
                }
            ]
        }
        mock_client.get.return_value = mock_response

        result = await news_service._fetch_news(mock_client, "Acme", 5)

        assert result is not None
        assert "**Test Article**" in result
        mock_client.get.assert_called_once_with(
            news_service.base_url,
            params={
                "engine": "google_news",
                "q": "Acme",
                "api_key": "test_api_key",
            },
            timeout=15.0,
        )

    @pytest.mark.asyncio
    async def test_non_200_returns_none(self, news_service):
        """Test that non-200 response returns None."""
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Server error"
        mock_client.get.return_value = mock_response

        result = await news_service._fetch_news(mock_client, "Acme", 5)

        assert result is None

    @pytest.mark.asyncio
    async def test_no_articles_returns_none(self, news_service):
        """Test that response with no articles returns None."""
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"news_results": []}
        mock_client.get.return_value = mock_response

        result = await news_service._fetch_news(mock_client, "Acme", 5)

        assert result is None

    @pytest.mark.asyncio
    async def test_respects_max_articles(self, news_service):
        """Test that max_articles limit is respected."""
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        articles = [
            {
                "title": f"Article {i}",
                "source": {"name": "Test Source"},
                "date": "2024-01-01",
                "snippet": f"Snippet {i}",
                "link": f"https://example.com/{i}"
            }
            for i in range(10)
        ]
        mock_response.json.return_value = {"news_results": articles}
        mock_client.get.return_value = mock_response

        result = await news_service._fetch_news(mock_client, "Acme", 3)

        assert result is not None
        # Count occurrences of article titles
        assert result.count("**Article") == 3
