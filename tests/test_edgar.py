import json
import os
import tempfile
import time
from datetime import datetime
from unittest.mock import MagicMock, AsyncMock, patch, mock_open

import pytest
from httpx import Response, HTTPStatusError, RequestError

from services.edgar import EdgarService


@pytest.fixture
def edgar_service():
    """Create an EdgarService instance for testing."""
    return EdgarService()


@pytest.fixture
def sample_sec_data():
    """Sample SEC tickers data."""
    return {
        "0": {
            "cik_str": 320193,
            "ticker": "AAPL",
            "title": "Apple Inc."
        },
        "1": {
            "cik_str": 1018724,
            "ticker": "AMZN",
            "title": "AMAZON COM INC"
        },
        "2": {
            "cik_str": 789019,
            "ticker": "MSFT",
            "title": "MICROSOFT CORP"
        }
    }


@pytest.fixture
def sample_submissions():
    """Sample SEC submissions data."""
    return {
        "cik": "0000320193",
        "entityType": "operating",
        "sic": "3571",
        "sicDescription": "Electronic Computers",
        "name": "Apple Inc.",
        "filings": {
            "recent": {
                "accessionNumber": [
                    "0000320193-23-000077",
                    "0000320193-23-000064",
                    "0000320193-23-000050",
                    "0000320193-23-000040",
                    "0000320193-23-000030"
                ],
                "filingDate": [
                    "2023-08-04",
                    "2023-05-05",
                    "2023-02-03",
                    "2023-01-15",
                    "2023-01-10"
                ],
                "reportDate": [
                    "2023-07-01",
                    "2023-04-01",
                    "2022-12-31",
                    "2023-01-10",
                    "2023-01-05"
                ],
                "acceptanceDateTime": [
                    "2023-08-04T16:30:00.000Z",
                    "2023-05-05T16:30:00.000Z",
                    "2023-02-03T16:30:00.000Z",
                    "2023-01-15T16:30:00.000Z",
                    "2023-01-10T16:30:00.000Z"
                ],
                "form": [
                    "10-Q",
                    "10-Q",
                    "10-K",
                    "8-K",
                    "8-K"
                ],
                "primaryDocument": [
                    "aapl-20230701.htm",
                    "aapl-20230401.htm",
                    "aapl-20221231.htm",
                    "aapl-20230110.htm",
                    "aapl-20230105.htm"
                ],
                "primaryDocDescription": [
                    "10-Q",
                    "10-Q",
                    "10-K",
                    "8-K",
                    "8-K"
                ],
                "items": [
                    "",
                    "",
                    "",
                    "5.02",
                    "1.01"
                ]
            }
        }
    }


class TestBuildLookup:
    """Tests for _build_lookup method."""

    def test_build_lookup_zero_padded_cik(self, edgar_service, sample_sec_data):
        """Test that CIK is zero-padded to 10 digits."""
        lookup = edgar_service._build_lookup(sample_sec_data)

        # Check that CIKs are zero-padded to 10 digits
        assert lookup["apple inc."]["cik"] == "0000320193"
        assert lookup["aapl"]["cik"] == "0000320193"
        assert lookup["amazon com inc"]["cik"] == "0001018724"
        assert lookup["amzn"]["cik"] == "0001018724"
        assert lookup["microsoft corp"]["cik"] == "0000789019"
        assert lookup["msft"]["cik"] == "0000789019"

    def test_build_lookup_lowercase_keys(self, edgar_service, sample_sec_data):
        """Test that all keys are lowercase."""
        lookup = edgar_service._build_lookup(sample_sec_data)

        # All keys should be lowercase
        assert "apple inc." in lookup
        assert "aapl" in lookup
        assert "AAPL" not in lookup
        assert "Apple Inc." not in lookup

    def test_build_lookup_includes_ticker_and_name(self, edgar_service, sample_sec_data):
        """Test that lookup includes both ticker and company name."""
        lookup = edgar_service._build_lookup(sample_sec_data)

        # Both ticker and name should be present
        assert "aapl" in lookup
        assert "apple inc." in lookup
        assert lookup["aapl"]["ticker"] == "AAPL"
        assert lookup["apple inc."]["ticker"] == "AAPL"


class TestLoadDiskCache:
    """Tests for _load_disk_cache method."""

    def test_load_disk_cache_file_exists_and_fresh(self, edgar_service):
        """Test loading fresh cache file."""
        cache_data = {"test": "data"}

        with patch('os.path.exists', return_value=True), \
             patch('os.path.getmtime', return_value=time.time()), \
             patch('builtins.open', mock_open(read_data=json.dumps(cache_data))):
            result = edgar_service._load_disk_cache()
            assert result == cache_data

    def test_load_disk_cache_file_does_not_exist(self, edgar_service):
        """Test when cache file doesn't exist."""
        with patch('os.path.exists', return_value=False):
            result = edgar_service._load_disk_cache()
            assert result is None

    def test_load_disk_cache_file_too_old(self, edgar_service):
        """Test when cache file is older than 24 hours."""
        old_time = time.time() - (25 * 60 * 60)  # 25 hours ago

        with patch('os.path.exists', return_value=True), \
             patch('os.path.getmtime', return_value=old_time):
            result = edgar_service._load_disk_cache()
            assert result is None

    def test_load_disk_cache_json_error(self, edgar_service):
        """Test when JSON decoding fails."""
        with patch('os.path.exists', return_value=True), \
             patch('os.path.getmtime', return_value=time.time()), \
             patch('builtins.open', mock_open(read_data="invalid json")):
            result = edgar_service._load_disk_cache()
            assert result is None


class TestSaveDiskCache:
    """Tests for _save_disk_cache method."""

    def test_save_disk_cache_success(self, edgar_service):
        """Test successful cache save."""
        cache_data = {"test": "data"}
        m = mock_open()

        with patch('builtins.open', m):
            edgar_service._save_disk_cache(cache_data)
            m.assert_called_once()
            handle = m()
            written_data = ''.join(call.args[0] for call in handle.write.call_args_list)
            assert json.loads(written_data) == cache_data

    def test_save_disk_cache_exception_caught(self, edgar_service):
        """Test that exceptions are caught during save."""
        cache_data = {"test": "data"}

        with patch('builtins.open', side_effect=Exception("Write error")):
            # Should not raise exception
            edgar_service._save_disk_cache(cache_data)


class TestLoadTickers:
    """Tests for _load_tickers method."""

    @pytest.mark.asyncio
    async def test_load_tickers_from_memory_cache(self, edgar_service, sample_sec_data):
        """Test loading tickers from memory cache."""
        # Set memory cache
        edgar_service._tickers_cache = sample_sec_data

        mock_client = AsyncMock()
        result = await edgar_service._load_tickers(mock_client)

        assert result == sample_sec_data
        # Client should not be called
        mock_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_load_tickers_from_disk_cache(self, edgar_service, sample_sec_data):
        """Test loading tickers from disk cache."""
        mock_client = AsyncMock()

        with patch.object(edgar_service, '_load_disk_cache', return_value=sample_sec_data):
            result = await edgar_service._load_tickers(mock_client)

            # _load_tickers calls _build_lookup on disk cache data
            assert "apple inc." in result
            assert "aapl" in result
            assert result["aapl"]["cik"] == "0000320193"
            mock_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_load_tickers_from_api(self, edgar_service, sample_sec_data):
        """Test fetching tickers from SEC API."""
        mock_client = AsyncMock()
        mock_response = MagicMock(status_code=200)
        mock_response.json.return_value = sample_sec_data
        mock_client.get.return_value = mock_response

        with patch.object(edgar_service, '_load_disk_cache', return_value=None), \
             patch.object(edgar_service, '_save_disk_cache') as mock_save:
            result = await edgar_service._load_tickers(mock_client)

            assert "aapl" in result
            assert result["apple inc."]["ticker"] == "AAPL"
            mock_client.get.assert_called_once()
            mock_save.assert_called_once_with(sample_sec_data)

    @pytest.mark.asyncio
    async def test_load_tickers_api_failure_returns_empty(self, edgar_service):
        """Test that API failure returns empty dict."""
        mock_client = AsyncMock()
        mock_response = MagicMock(status_code=500)
        mock_client.get.return_value = mock_response

        with patch.object(edgar_service, '_load_disk_cache', return_value=None):
            result = await edgar_service._load_tickers(mock_client)

            assert result == {}


class TestMatchCompany:
    """Tests for _match_company method."""

    def test_match_company_direct_match(self, edgar_service, sample_sec_data):
        """Test direct company name match."""
        lookup = edgar_service._build_lookup(sample_sec_data)
        result = edgar_service._match_company("Apple Inc.", lookup)

        assert result is not None
        assert result["ticker"] == "AAPL"
        assert result["cik"] == "0000320193"

    def test_match_company_with_suffix(self, edgar_service, sample_sec_data):
        """Test matching company by adding common suffix."""
        lookup = edgar_service._build_lookup(sample_sec_data)
        # "apple" + " inc." = "apple inc." which is in lookup
        result = edgar_service._match_company("Apple", lookup)

        assert result is not None
        assert result["ticker"] == "AAPL"

    def test_match_company_domain_suffix_stripping(self, edgar_service):
        """Test matching by stripping domain suffix (.com)."""
        data = {
            "0": {
                "cik_str": 123456,
                "ticker": "TEST",
                "title": "Acmewidgets"
            }
        }
        lookup = edgar_service._build_lookup(data)
        result = edgar_service._match_company("acmewidgets.com", lookup)

        assert result is not None
        assert result["ticker"] == "TEST"

    def test_match_company_filler_stripping(self, edgar_service):
        """Test matching with filler stripping (datadoghq -> datadog)."""
        data = {
            "0": {
                "cik_str": 123456,
                "ticker": "DDOG",
                "title": "Datadog, Inc."
            }
        }
        lookup = edgar_service._build_lookup(data)
        result = edgar_service._match_company("DatadogHQ", lookup)

        assert result is not None
        assert result["ticker"] == "DDOG"

    def test_match_company_substring_match(self, edgar_service, sample_sec_data):
        """Test substring matching."""
        lookup = edgar_service._build_lookup(sample_sec_data)
        result = edgar_service._match_company("Microsoft", lookup)

        assert result is not None
        assert result["ticker"] == "MSFT"

    def test_match_company_no_match(self, edgar_service, sample_sec_data):
        """Test when no match is found."""
        lookup = edgar_service._build_lookup(sample_sec_data)
        result = edgar_service._match_company("Nonexistent Company XYZ", lookup)

        assert result is None


class TestExtract8kEvents:
    """Tests for _extract_8k_events method."""

    def test_extract_8k_events_with_high_signal_items(self, edgar_service):
        """Test extracting 8-K events with high-signal items."""
        submissions = {
            "filings": {
                "recent": {
                    "form": ["8-K", "10-K"],
                    "filingDate": ["2023-01-15", "2023-02-01"],
                    "items": ["1.01", ""],
                    "primaryDocument": ["doc1.htm", "doc2.htm"],
                    "accessionNumber": ["acc1", "acc2"]
                }
            }
        }

        result = edgar_service._extract_8k_events(submissions)

        assert result is not None
        assert "⚡" in result  # High signal indicator
        assert "Entry into a Material Definitive Agreement" in result

    def test_extract_8k_events_with_regular_items(self, edgar_service):
        """Test extracting 8-K events with regular items."""
        submissions = {
            "filings": {
                "recent": {
                    "form": ["8-K"],
                    "filingDate": ["2023-01-15"],
                    "items": ["2.02"],
                    "primaryDocument": ["doc1.htm"],
                    "accessionNumber": ["acc1"]
                }
            }
        }

        result = edgar_service._extract_8k_events(submissions)

        assert result is not None
        assert "⚡" not in result  # Not high signal
        assert "Results of Operations" in result

    def test_extract_8k_events_no_8k_filings(self, edgar_service):
        """Test when there are no 8-K filings."""
        submissions = {
            "filings": {
                "recent": {
                    "form": ["10-K", "10-Q"],
                    "filingDate": ["2023-01-15", "2023-02-01"],
                    "items": ["", ""],
                    "primaryDocument": ["doc1.htm", "doc2.htm"],
                    "accessionNumber": ["acc1", "acc2"]
                }
            }
        }

        result = edgar_service._extract_8k_events(submissions)

        assert result is None


class TestExtractAnnualFilings:
    """Tests for _extract_annual_filings method."""

    def test_extract_annual_filings_mixed(self, edgar_service):
        """Test extracting mixed 10-K and 10-Q filings."""
        submissions = {
            "filings": {
                "recent": {
                    "form": ["10-K", "10-Q", "10-Q", "10-K", "8-K"],
                    "filingDate": ["2023-02-01", "2023-05-01", "2023-08-01", "2022-02-01", "2023-01-15"],
                    "reportDate": ["2022-12-31", "2023-03-31", "2023-06-30", "2021-12-31", ""],
                }
            }
        }

        result = edgar_service._extract_annual_filings(submissions)

        assert result is not None
        assert "10-K" in result
        assert "10-Q" in result
        assert result.count("**10-K**") == 2
        assert result.count("**10-Q**") == 2  # Only 2 of 3 possible, since we only have 2 10-Q before limit

    def test_extract_annual_filings_none_found(self, edgar_service):
        """Test when no annual filings are found."""
        submissions = {
            "filings": {
                "recent": {
                    "form": ["8-K", "8-K"],
                    "filingDate": ["2023-01-15", "2023-02-01"],
                    "primaryDocument": ["8k1.htm", "8k2.htm"],
                    "accessionNumber": ["acc1", "acc2"]
                }
            }
        }

        result = edgar_service._extract_annual_filings(submissions)

        assert result is None


class TestParseRiskFactors:
    """Tests for _parse_risk_factors method."""

    def test_parse_risk_factors_finds_section(self, edgar_service):
        """Test that risk factors section is found and extracted."""
        html = """
        <html>
        <body>
        <p>Some content before</p>
        <p>Item 1A. Risk Factors</p>
        <p>These are the risk factors for our business. We face many risks including market volatility,
        competition, regulatory changes, and technological disruption. Our business model depends on
        continued customer adoption and retention. We may face challenges in scaling our operations.</p>
        <p>Item 1B. Unresolved Staff Comments</p>
        <p>Some content after</p>
        </body>
        </html>
        """

        result = edgar_service._parse_risk_factors(html)

        assert result is not None
        assert "risk factors" in result.lower()
        assert "market volatility" in result.lower()
        assert len(result) <= 6000

    def test_parse_risk_factors_no_match_returns_none(self, edgar_service):
        """Test that no match returns None."""
        html = """
        <html>
        <body>
        <p>Some content without risk factors section</p>
        </body>
        </html>
        """

        result = edgar_service._parse_risk_factors(html)

        assert result is None

    def test_parse_risk_factors_short_text_returns_none(self, edgar_service):
        """Test that short text (<200 chars) returns None."""
        html = """
        <html>
        <body>
        <p>Item 1A. Risk Factors</p>
        <p>Short text.</p>
        <p>Item 1B. Unresolved Staff Comments</p>
        </body>
        </html>
        """

        result = edgar_service._parse_risk_factors(html)

        assert result is None


class TestGetCompanyFilings:
    """Tests for get_company_filings method."""

    @pytest.mark.asyncio
    async def test_get_company_filings_exception_returns_none(self, edgar_service):
        """Test that exception returns None."""
        with patch.object(edgar_service, '_get_company_filings_impl', side_effect=Exception("Error")):
            result = await edgar_service.get_company_filings("Apple Inc.")

            assert result is None

    @pytest.mark.asyncio
    async def test_get_company_filings_creates_client_if_none(self, edgar_service, sample_sec_data):
        """Test that client is created if None is passed."""
        with patch.object(edgar_service, '_load_tickers', return_value=sample_sec_data), \
             patch.object(edgar_service, '_match_company', return_value=None):
            result = await edgar_service.get_company_filings("Apple Inc.", client=None)

            # Should not raise exception even though client was None
            assert result is None


class TestGetSubmissions:
    """Tests for _get_submissions method."""

    @pytest.mark.asyncio
    async def test_get_submissions_success(self, edgar_service, sample_submissions):
        """Test successful submissions retrieval."""
        mock_client = AsyncMock()
        mock_response = MagicMock(status_code=200)
        mock_response.json.return_value = sample_submissions
        mock_client.get.return_value = mock_response

        result = await edgar_service._get_submissions(mock_client, "0000320193")

        assert result == sample_submissions
        mock_client.get.assert_called_once()
        call_args = mock_client.get.call_args
        assert "0000320193.json" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_get_submissions_http_error_returns_none(self, edgar_service):
        """Test that HTTP error returns None."""
        mock_client = AsyncMock()
        mock_response = MagicMock(status_code=404)
        mock_client.get.return_value = mock_response

        result = await edgar_service._get_submissions(mock_client, "0000320193")

        assert result is None

