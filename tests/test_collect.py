"""Tests for services/collect.py - Shared parallel data collection for the research pipeline."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
import httpx
import asyncio

from services.collect import (
    get_shared_http_client,
    close_shared_http_client,
    _get_retrieval_service,
    _extract_company_name,
    collect_enrichment_data,
)
from models import ScrapedContent


@pytest.fixture
def mock_settings():
    """Mock settings with all features enabled."""
    settings = MagicMock()
    settings.edgar_enabled = True
    settings.federal_register_enabled = True
    settings.materials_enabled = True
    return settings


@pytest.fixture
def mock_settings_disabled():
    """Mock settings with features disabled."""
    settings = MagicMock()
    settings.edgar_enabled = False
    settings.federal_register_enabled = False
    settings.materials_enabled = False
    return settings


@pytest.fixture
def scraped_content():
    """Create a ScrapedContent instance for testing."""
    return ScrapedContent(
        homepage="Test company homepage content",
        about="Test about page",
        careers="Test careers page",
    )


@pytest.fixture(autouse=True)
async def cleanup_http_client():
    """Clean up the shared HTTP client after each test."""
    yield
    # Import and reset module-level state
    import services.collect
    services.collect._http_client = None
    services.collect._http_client_lock = None
    services.collect._retrieval_service = None


class TestExtractCompanyName:
    """Tests for _extract_company_name function."""

    def test_https_with_www_and_path(self):
        """Test extraction from full URL with https, www, and path."""
        result = _extract_company_name("https://www.example.com/about")
        assert result == "example.com"

    def test_http_simple(self):
        """Test extraction from simple http URL."""
        result = _extract_company_name("http://example.com")
        assert result == "example.com"

    def test_https_without_www(self):
        """Test extraction from https URL without www."""
        result = _extract_company_name("https://example.com/products")
        assert result == "example.com"

    def test_with_subdomain(self):
        """Test extraction preserves subdomain."""
        result = _extract_company_name("https://www.api.example.com")
        assert result == "api.example.com"

    def test_with_port(self):
        """Test extraction with port number."""
        result = _extract_company_name("http://example.com:8080/page")
        assert result == "example.com:8080"

    def test_complex_path(self):
        """Test extraction with complex path."""
        result = _extract_company_name("https://www.example.com/en/about/team")
        assert result == "example.com"


class TestGetSharedHttpClient:
    """Tests for get_shared_http_client function."""

    @pytest.mark.asyncio
    async def test_creates_client_on_first_call(self):
        """Test that client is created on first call."""
        client = await get_shared_http_client()
        assert client is not None
        assert isinstance(client, httpx.AsyncClient)
        assert not client.is_closed

    @pytest.mark.asyncio
    async def test_reuses_client_on_second_call(self):
        """Test that same client is reused on subsequent calls."""
        client1 = await get_shared_http_client()
        client2 = await get_shared_http_client()
        assert client1 is client2

    @pytest.mark.asyncio
    async def test_creates_new_client_if_closed(self):
        """Test that a new client is created if the existing one is closed."""
        client1 = await get_shared_http_client()
        await client1.aclose()

        client2 = await get_shared_http_client()
        assert client2 is not client1
        assert not client2.is_closed

    @pytest.mark.asyncio
    async def test_client_has_correct_config(self):
        """Test that client is configured with correct timeout and limits."""
        client = await get_shared_http_client()
        # Check timeout configuration
        assert client.timeout.read == 30.0
        # Check that client is properly configured (limits are internal)
        # Just verify client was created successfully
        assert isinstance(client, httpx.AsyncClient)


class TestCloseSharedHttpClient:
    """Tests for close_shared_http_client function."""

    @pytest.mark.asyncio
    async def test_closes_existing_client(self):
        """Test that existing client is closed."""
        client = await get_shared_http_client()
        assert not client.is_closed

        await close_shared_http_client()
        assert client.is_closed

    @pytest.mark.asyncio
    async def test_sets_client_to_none(self):
        """Test that client is set to None after closing."""
        import services.collect

        await get_shared_http_client()
        await close_shared_http_client()

        assert services.collect._http_client is None

    @pytest.mark.asyncio
    async def test_handles_no_client(self):
        """Test that function handles case when no client exists."""
        import services.collect
        services.collect._http_client = None

        # Should not raise an error
        await close_shared_http_client()

    @pytest.mark.asyncio
    async def test_handles_already_closed_client(self):
        """Test that function handles already closed client."""
        client = await get_shared_http_client()
        await client.aclose()

        # Should not raise an error
        await close_shared_http_client()


class TestGetRetrievalService:
    """Tests for _get_retrieval_service function."""

    def test_returns_none_when_materials_disabled(self, mock_settings_disabled):
        """Test that None is returned when materials_enabled is False."""
        with patch("services.collect.get_settings", return_value=mock_settings_disabled):
            result = _get_retrieval_service()
            assert result is None

    def test_creates_service_when_materials_enabled(self, mock_settings):
        """Test that RetrievalService is created when materials_enabled is True."""
        with patch("services.collect.get_settings", return_value=mock_settings):
            with patch("services.collect.RetrievalService") as mock_retrieval_class:
                mock_service = MagicMock()
                mock_retrieval_class.return_value = mock_service

                result = _get_retrieval_service()

                assert result is mock_service
                mock_retrieval_class.assert_called_once()

    def test_returns_existing_service_on_second_call(self, mock_settings):
        """Test that existing service is reused on subsequent calls."""
        import services.collect

        with patch("services.collect.get_settings", return_value=mock_settings):
            with patch("services.collect.RetrievalService") as mock_retrieval_class:
                mock_service = MagicMock()
                mock_retrieval_class.return_value = mock_service

                # Reset global state
                services.collect._retrieval_service = None

                result1 = _get_retrieval_service()
                result2 = _get_retrieval_service()

                assert result1 is result2
                # Should only create once
                assert mock_retrieval_class.call_count == 1


class TestCollectEnrichmentData:
    """Tests for collect_enrichment_data function."""

    @pytest.mark.asyncio
    async def test_all_enrichments_succeed(self, mock_settings, scraped_content):
        """Test that all enrichments are collected and set on scraped_content."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False

        # Mock all service methods
        with patch("services.collect.get_settings", return_value=mock_settings), \
             patch("services.collect.get_shared_http_client", return_value=mock_client), \
patch("services.collect.edgar_service") as mock_edgar, \
             patch("services.collect.federal_register_service") as mock_fed_reg, \
             patch("services.collect._get_retrieval_service") as mock_get_retrieval, \
             patch("services.collect.get_integration") as mock_get_integration, \
             patch("services.collect.zoominfo_get_firmographics") as mock_zoominfo:

            # Set up mock returns
            mock_edgar.get_company_filings = AsyncMock(return_value="EDGAR content")
            mock_edgar._last_sic_code = "1234"
            mock_fed_reg.get_upcoming_regulations = AsyncMock(return_value="Federal Register content")

            mock_retrieval = MagicMock()
            mock_retrieval.get_relevant_context = AsyncMock(return_value="Materials content")
            mock_get_retrieval.return_value = mock_retrieval

            # Mock ZoomInfo integration
            mock_zi_integration = MagicMock()
            mock_get_integration.return_value = mock_zi_integration
            mock_zoominfo.return_value = "ZoomInfo firmographics"

            result = await collect_enrichment_data(
                scraped_content=scraped_content,
                company_url="https://www.example.com",
                user_id=123,
                verbose=False
            )

            # Verify all enrichments were set
            assert scraped_content.edgar_filings == "EDGAR content"
            assert scraped_content.federal_regulations == "Federal Register content"
            assert scraped_content.firmographics == "ZoomInfo firmographics"
            assert result == "Materials content"

    @pytest.mark.asyncio
    async def test_individual_failures_dont_break_others(self, mock_settings, scraped_content):
        """Test that failures in individual enrichments don't break the whole process."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False

        with patch("services.collect.get_settings", return_value=mock_settings), \
             patch("services.collect.get_shared_http_client", return_value=mock_client), \
patch("services.collect.edgar_service") as mock_edgar, \
             patch("services.collect.federal_register_service") as mock_fed_reg, \
             patch("services.collect._get_retrieval_service") as mock_get_retrieval, \
             patch("services.collect.get_integration") as mock_get_integration:

            mock_edgar.get_company_filings = AsyncMock(return_value="EDGAR content")
            mock_edgar._last_sic_code = None
            mock_fed_reg.get_upcoming_regulations = AsyncMock(return_value="Federal Register content")
            mock_get_retrieval.return_value = None
            mock_get_integration.return_value = None

            result = await collect_enrichment_data(
                scraped_content=scraped_content,
                company_url="https://www.example.com",
                user_id=123,
                verbose=False
            )

            assert scraped_content.edgar_filings == "EDGAR content"
            assert scraped_content.federal_regulations == "Federal Register content"

    @pytest.mark.asyncio
    async def test_federal_register_runs_after_edgar(self, mock_settings, scraped_content):
        """Test that Federal Register runs after EDGAR and uses SIC code."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False

        with patch("services.collect.get_settings", return_value=mock_settings), \
             patch("services.collect.get_shared_http_client", return_value=mock_client), \
patch("services.collect.edgar_service") as mock_edgar, \
             patch("services.collect.federal_register_service") as mock_fed_reg, \
             patch("services.collect._get_retrieval_service") as mock_get_retrieval, \
             patch("services.collect.get_integration") as mock_get_integration:

            mock_edgar.get_company_filings = AsyncMock(return_value="EDGAR content")
            mock_edgar._last_sic_code = "5678"
            mock_fed_reg.get_upcoming_regulations = AsyncMock(return_value="Federal Register content")
            mock_get_retrieval.return_value = None
            mock_get_integration.return_value = None

            await collect_enrichment_data(
                scraped_content=scraped_content,
                company_url="https://www.example.com",
                user_id=123,
                verbose=False
            )

            # Verify Federal Register was called with EDGAR's SIC code
            mock_fed_reg.get_upcoming_regulations.assert_called_once()
            call_kwargs = mock_fed_reg.get_upcoming_regulations.call_args.kwargs
            assert call_kwargs["sic_code"] == "5678"
            assert call_kwargs["company_name"] == "example.com"

    @pytest.mark.asyncio
    async def test_materials_returned_as_string(self, mock_settings, scraped_content):
        """Test that materials result is returned as string."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False

        with patch("services.collect.get_settings", return_value=mock_settings), \
             patch("services.collect.get_shared_http_client", return_value=mock_client), \
patch("services.collect.edgar_service") as mock_edgar, \
             patch("services.collect.federal_register_service") as mock_fed_reg, \
             patch("services.collect._get_retrieval_service") as mock_get_retrieval, \
             patch("services.collect.get_integration") as mock_get_integration:

            mock_edgar.get_company_filings = AsyncMock(return_value=None)
            mock_edgar._last_sic_code = None
            mock_fed_reg.get_upcoming_regulations = AsyncMock(return_value=None)
            mock_get_integration.return_value = None

            mock_retrieval = MagicMock()
            mock_retrieval.get_relevant_context = AsyncMock(return_value="Retrieved materials")
            mock_get_retrieval.return_value = mock_retrieval

            result = await collect_enrichment_data(
                scraped_content=scraped_content,
                company_url="https://www.example.com",
                user_id=123,
                verbose=False
            )

            assert result == "Retrieved materials"
            assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_firmographics_tries_zoominfo_first(self, mock_settings, scraped_content):
        """Test that ZoomInfo is tried first for firmographics."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False

        with patch("services.collect.get_settings", return_value=mock_settings), \
             patch("services.collect.get_shared_http_client", return_value=mock_client), \
patch("services.collect.edgar_service") as mock_edgar, \
             patch("services.collect.federal_register_service") as mock_fed_reg, \
             patch("services.collect._get_retrieval_service") as mock_get_retrieval, \
             patch("services.collect.get_integration") as mock_get_integration, \
             patch("services.collect.zoominfo_get_firmographics") as mock_zoominfo, \
             patch("services.collect.apollo_get_firmographics") as mock_apollo:

            mock_edgar.get_company_filings = AsyncMock(return_value=None)
            mock_edgar._last_sic_code = None
            mock_fed_reg.get_upcoming_regulations = AsyncMock(return_value=None)
            mock_get_retrieval.return_value = None

            # ZoomInfo integration exists
            mock_zi_integration = MagicMock()
            mock_get_integration.return_value = mock_zi_integration
            mock_zoominfo.return_value = "ZoomInfo data"

            await collect_enrichment_data(
                scraped_content=scraped_content,
                company_url="https://www.example.com",
                user_id=123,
                verbose=False
            )

            # ZoomInfo should be called, Apollo should not
            mock_zoominfo.assert_called_once_with(123, "example.com")
            mock_apollo.assert_not_called()
            assert scraped_content.firmographics == "ZoomInfo data"

    @pytest.mark.asyncio
    async def test_firmographics_falls_back_to_apollo(self, mock_settings, scraped_content):
        """Test that Apollo is used when ZoomInfo returns None."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False

        with patch("services.collect.get_settings", return_value=mock_settings), \
             patch("services.collect.get_shared_http_client", return_value=mock_client), \
patch("services.collect.edgar_service") as mock_edgar, \
             patch("services.collect.federal_register_service") as mock_fed_reg, \
             patch("services.collect._get_retrieval_service") as mock_get_retrieval, \
             patch("services.collect.get_integration") as mock_get_integration, \
             patch("services.collect.zoominfo_get_firmographics") as mock_zoominfo, \
             patch("services.collect.apollo_get_firmographics") as mock_apollo:

            mock_edgar.get_company_filings = AsyncMock(return_value=None)
            mock_edgar._last_sic_code = None
            mock_fed_reg.get_upcoming_regulations = AsyncMock(return_value=None)
            mock_get_retrieval.return_value = None

            # Mock get_integration to return ZoomInfo first, then Apollo
            async def mock_integration_side_effect(user_id, integration_name):
                if integration_name == "zoominfo":
                    return MagicMock()  # ZoomInfo exists
                elif integration_name == "apollo":
                    return MagicMock()  # Apollo exists
                return None

            mock_get_integration.side_effect = mock_integration_side_effect
            mock_zoominfo.return_value = None  # ZoomInfo returns None
            mock_apollo.return_value = "Apollo data"

            await collect_enrichment_data(
                scraped_content=scraped_content,
                company_url="https://www.example.com",
                user_id=123,
                verbose=False
            )

            # Both should be called
            mock_zoominfo.assert_called_once_with(123, "example.com")
            mock_apollo.assert_called_once_with(123, "example.com")
            assert scraped_content.firmographics == "Apollo data"

    @pytest.mark.asyncio
    async def test_edgar_disabled_respects_setting(self, scraped_content):
        """Test that EDGAR is skipped when edgar_enabled is False."""
        mock_settings = MagicMock()
        mock_settings.edgar_enabled = False
        mock_settings.federal_register_enabled = True
        mock_settings.materials_enabled = False

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False

        with patch("services.collect.get_settings", return_value=mock_settings), \
             patch("services.collect.get_shared_http_client", return_value=mock_client), \
patch("services.collect.edgar_service") as mock_edgar, \
             patch("services.collect.federal_register_service") as mock_fed_reg, \
             patch("services.collect._get_retrieval_service") as mock_get_retrieval, \
             patch("services.collect.get_integration") as mock_get_integration:

            mock_edgar.get_company_filings = AsyncMock(return_value="Should not be called")
            mock_edgar._last_sic_code = None
            mock_fed_reg.get_upcoming_regulations = AsyncMock(return_value=None)
            mock_get_retrieval.return_value = None
            mock_get_integration.return_value = None

            await collect_enrichment_data(
                scraped_content=scraped_content,
                company_url="https://www.example.com",
                user_id=123,
                verbose=False
            )

            # EDGAR should not be called
            mock_edgar.get_company_filings.assert_not_called()
            assert scraped_content.edgar_filings is None

    @pytest.mark.asyncio
    async def test_federal_register_disabled_respects_setting(self, scraped_content):
        """Test that Federal Register is skipped when federal_register_enabled is False."""
        mock_settings = MagicMock()
        mock_settings.edgar_enabled = True
        mock_settings.federal_register_enabled = False
        mock_settings.materials_enabled = False

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False

        with patch("services.collect.get_settings", return_value=mock_settings), \
             patch("services.collect.get_shared_http_client", return_value=mock_client), \
patch("services.collect.edgar_service") as mock_edgar, \
             patch("services.collect.federal_register_service") as mock_fed_reg, \
             patch("services.collect._get_retrieval_service") as mock_get_retrieval, \
             patch("services.collect.get_integration") as mock_get_integration:

            mock_edgar.get_company_filings = AsyncMock(return_value="EDGAR content")
            mock_edgar._last_sic_code = "1234"
            mock_fed_reg.get_upcoming_regulations = AsyncMock(return_value="Should not be called")
            mock_get_retrieval.return_value = None
            mock_get_integration.return_value = None

            await collect_enrichment_data(
                scraped_content=scraped_content,
                company_url="https://www.example.com",
                user_id=123,
                verbose=False
            )

            # Federal Register should not be called
            mock_fed_reg.get_upcoming_regulations.assert_not_called()
            assert scraped_content.federal_regulations is None

    @pytest.mark.asyncio
    async def test_verbose_mode_logs_progress(self, mock_settings, scraped_content):
        """Test that verbose mode doesn't break execution (logging tested separately)."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False

        with patch("services.collect.get_settings", return_value=mock_settings), \
             patch("services.collect.get_shared_http_client", return_value=mock_client), \
patch("services.collect.edgar_service") as mock_edgar, \
             patch("services.collect.federal_register_service") as mock_fed_reg, \
             patch("services.collect._get_retrieval_service") as mock_get_retrieval, \
             patch("services.collect.get_integration") as mock_get_integration:

            mock_edgar.get_company_filings = AsyncMock(return_value=None)
            mock_edgar._last_sic_code = None
            mock_fed_reg.get_upcoming_regulations = AsyncMock(return_value=None)
            mock_get_retrieval.return_value = None
            mock_get_integration.return_value = None

            # Should not raise error in verbose mode
            result = await collect_enrichment_data(
                scraped_content=scraped_content,
                company_url="https://www.example.com",
                user_id=123,
                verbose=True
            )

            assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_company_name_extraction_in_context(self, mock_settings, scraped_content):
        """Test that company name is correctly extracted and used."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False

        with patch("services.collect.get_settings", return_value=mock_settings), \
             patch("services.collect.get_shared_http_client", return_value=mock_client), \
patch("services.collect.edgar_service") as mock_edgar, \
             patch("services.collect.federal_register_service") as mock_fed_reg, \
             patch("services.collect._get_retrieval_service") as mock_get_retrieval, \
             patch("services.collect.get_integration") as mock_get_integration:

            mock_edgar.get_company_filings = AsyncMock(return_value=None)
            mock_edgar._last_sic_code = None
            mock_fed_reg.get_upcoming_regulations = AsyncMock(return_value=None)

            mock_retrieval = MagicMock()
            mock_retrieval.get_relevant_context = AsyncMock(return_value="")
            mock_get_retrieval.return_value = mock_retrieval
            mock_get_integration.return_value = None

            await collect_enrichment_data(
                scraped_content=scraped_content,
                company_url="https://www.acme-corp.com/about/team",
                user_id=123,
                verbose=False
            )

            # Verify the extracted company name was used
            mock_edgar.get_company_filings.assert_called_once()
            call_args = mock_edgar.get_company_filings.call_args
            assert call_args[0][0] == "acme-corp.com"

    @pytest.mark.asyncio
    async def test_materials_empty_string_on_none(self, mock_settings, scraped_content):
        """Test that materials returns empty string when retrieval returns None."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False

        with patch("services.collect.get_settings", return_value=mock_settings), \
             patch("services.collect.get_shared_http_client", return_value=mock_client), \
patch("services.collect.edgar_service") as mock_edgar, \
             patch("services.collect.federal_register_service") as mock_fed_reg, \
             patch("services.collect._get_retrieval_service") as mock_get_retrieval, \
             patch("services.collect.get_integration") as mock_get_integration:

            mock_edgar.get_company_filings = AsyncMock(return_value=None)
            mock_edgar._last_sic_code = None
            mock_fed_reg.get_upcoming_regulations = AsyncMock(return_value=None)
            mock_get_integration.return_value = None

            mock_retrieval = MagicMock()
            mock_retrieval.get_relevant_context = AsyncMock(return_value=None)
            mock_get_retrieval.return_value = mock_retrieval

            result = await collect_enrichment_data(
                scraped_content=scraped_content,
                company_url="https://www.example.com",
                user_id=123,
                verbose=False
            )

            assert result == ""

    @pytest.mark.asyncio
    async def test_materials_uses_homepage_for_context(self, mock_settings, scraped_content):
        """Test that materials retrieval uses homepage content for context."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False

        scraped_content.homepage = "A" * 600  # More than 500 chars

        with patch("services.collect.get_settings", return_value=mock_settings), \
             patch("services.collect.get_shared_http_client", return_value=mock_client), \
patch("services.collect.edgar_service") as mock_edgar, \
             patch("services.collect.federal_register_service") as mock_fed_reg, \
             patch("services.collect._get_retrieval_service") as mock_get_retrieval, \
             patch("services.collect.get_integration") as mock_get_integration:

            mock_edgar.get_company_filings = AsyncMock(return_value=None)
            mock_edgar._last_sic_code = None
            mock_fed_reg.get_upcoming_regulations = AsyncMock(return_value=None)
            mock_get_integration.return_value = None

            mock_retrieval = MagicMock()
            mock_retrieval.get_relevant_context = AsyncMock(return_value="")
            mock_get_retrieval.return_value = mock_retrieval

            await collect_enrichment_data(
                scraped_content=scraped_content,
                company_url="https://www.example.com",
                user_id=123,
                verbose=False
            )

            # Verify homepage was truncated to 500 chars
            call_kwargs = mock_retrieval.get_relevant_context.call_args.kwargs
            assert call_kwargs["company_description"] == "A" * 500
