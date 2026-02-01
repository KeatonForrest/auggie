import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock, AsyncMock
from services.federal_register import FederalRegisterService


@pytest.fixture
def service():
    return FederalRegisterService()


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.get = AsyncMock()
    return client


@pytest.fixture
def sample_regulation():
    return {
        "title": "Test Regulation",
        "type": "Rule",
        "agencies": [{"name": "Test Agency"}],
        "publication_date": "2025-01-15",
        "effective_on": "2025-02-15",
        "abstract": "This is a test regulation abstract."
    }


@pytest.fixture
def sample_proposed_regulation():
    return {
        "title": "Proposed Test Regulation",
        "type": "PRORULE",
        "agencies": [{"name": "Test Agency"}],
        "publication_date": "2025-01-15",
        "effective_on": None,
        "abstract": "This is a proposed regulation abstract."
    }


class TestGetUpcomingRegulations:
    @pytest.mark.asyncio
    async def test_with_sic_code(self, service, mock_client):
        """Test get_upcoming_regulations with a known SIC code."""
        with patch.object(service, '_get_regulations_impl', new_callable=AsyncMock) as mock_impl:
            mock_impl.return_value = "mocked results"

            result = await service.get_upcoming_regulations(
                company_name="Test Company",
                sic_code="7372",
                client=mock_client
            )

            assert result == "mocked results"
            mock_impl.assert_called_once()
            call_args = mock_impl.call_args[0]
            assert call_args[0] == mock_client
            # SIC 7372 -> first 2 digits = 73
            assert "data privacy" in str(call_args[1]).lower() or "cybersecurity" in str(call_args[1]).lower()

    @pytest.mark.asyncio
    async def test_with_industry_keywords(self, service, mock_client):
        """Test get_upcoming_regulations with industry keywords."""
        with patch.object(service, '_get_regulations_impl', new_callable=AsyncMock) as mock_impl:
            mock_impl.return_value = "mocked results"
            industry_keywords = ["healthcare", "medical devices"]

            result = await service.get_upcoming_regulations(
                company_name="Test Company",
                industry_keywords=industry_keywords,
                client=mock_client
            )

            assert result == "mocked results"
            mock_impl.assert_called_once()
            call_args = mock_impl.call_args[0]
            assert call_args[0] == mock_client
            assert call_args[1] == industry_keywords

    @pytest.mark.asyncio
    async def test_with_neither_uses_default_topics(self, service, mock_client):
        """Test get_upcoming_regulations without SIC code or keywords uses DEFAULT_TOPICS."""
        with patch.object(service, '_get_regulations_impl', new_callable=AsyncMock) as mock_impl:
            mock_impl.return_value = "mocked results"

            result = await service.get_upcoming_regulations(
                company_name="Test Company",
                client=mock_client
            )

            assert result == "mocked results"
            mock_impl.assert_called_once()
            call_args = mock_impl.call_args[0]
            assert call_args[0] == mock_client
            # Should use DEFAULT_TOPICS
            assert "data privacy" in call_args[1] or "cybersecurity regulation" in call_args[1]

    @pytest.mark.asyncio
    async def test_exception_returns_none(self, service, mock_client):
        """Test get_upcoming_regulations returns None on exception."""
        with patch.object(service, '_get_regulations_impl', new_callable=AsyncMock) as mock_impl:
            mock_impl.side_effect = Exception("Test error")

            result = await service.get_upcoming_regulations(
                company_name="Test Company",
                client=mock_client
            )

            assert result is None

    @pytest.mark.asyncio
    async def test_creates_client_if_none(self, service):
        """Test that client is created if None is provided."""
        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client_instance = MagicMock()
            mock_client_instance.get = AsyncMock(return_value=MagicMock(
                status_code=200,
                json=MagicMock(return_value={"results": []})
            ))
            mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_class.return_value.__aexit__ = AsyncMock()

            result = await service.get_upcoming_regulations(
                company_name="Test Company"
            )

            # Should have created a client
            mock_client_class.assert_called_once()


class TestSearchRegulations:
    @pytest.mark.asyncio
    async def test_success(self, service, mock_client, sample_regulation):
        """Test _search_regulations with successful response."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"results": [sample_regulation]}
        mock_client.get.return_value = mock_response

        result = await service._search_regulations(mock_client, "test term")

        assert result == [sample_regulation]
        mock_client.get.assert_called_once()
        call_args = mock_client.get.call_args
        assert "test term" in call_args[1]["params"]["conditions[term]"]
        assert "RULE" in call_args[1]["params"]["conditions[type][]"]

    @pytest.mark.asyncio
    async def test_http_error_returns_empty_list(self, service, mock_client):
        """Test _search_regulations returns [] on HTTP error."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = Exception("HTTP Error")
        mock_client.get.return_value = mock_response

        result = await service._search_regulations(mock_client, "test term")

        assert result == []

    @pytest.mark.asyncio
    async def test_exception_returns_empty_list(self, service, mock_client):
        """Test _search_regulations returns [] on exception."""
        mock_client.get.side_effect = Exception("Network error")

        result = await service._search_regulations(mock_client, "test term")

        assert result == []

    @pytest.mark.asyncio
    async def test_effective_date_parameter(self, service, mock_client):
        """Test that effective_date parameter is set to 6 months ago."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"results": []}
        mock_client.get.return_value = mock_response

        await service._search_regulations(mock_client, "test term")

        call_args = mock_client.get.call_args
        effective_date_param = call_args[1]["params"]["conditions[effective_date][gte]"]

        # Should be approximately 6 months ago
        six_months_ago = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")
        assert effective_date_param == six_months_ago or \
               abs((datetime.strptime(effective_date_param, "%Y-%m-%d") -
                    datetime.strptime(six_months_ago, "%Y-%m-%d")).days) <= 1


class TestGetRegulationsImpl:
    @pytest.mark.asyncio
    async def test_deduplicates_by_title(self, service, mock_client):
        """Test _get_regulations_impl deduplicates regulations by title."""
        duplicate_regs = [
            {"title": "Test Reg", "effective_on": "2025-03-01", "agencies": []},
            {"title": "Test Reg", "effective_on": "2025-03-02", "agencies": []},
            {"title": "Unique Reg", "effective_on": "2025-03-03", "agencies": []}
        ]

        with patch.object(service, '_search_regulations', new_callable=AsyncMock) as mock_search:
            mock_search.return_value = duplicate_regs
            with patch.object(service, '_format_results') as mock_format:
                mock_format.return_value = "formatted"

                await service._get_regulations_impl(mock_client, ["term1"])

                # Should only have 2 unique regulations
                formatted_regs = mock_format.call_args[0][0]
                assert len(formatted_regs) == 2
                titles = [r["title"] for r in formatted_regs]
                assert titles.count("Test Reg") == 1
                assert titles.count("Unique Reg") == 1

    @pytest.mark.asyncio
    async def test_sorts_by_effective_on(self, service, mock_client):
        """Test _get_regulations_impl sorts by effective_on date."""
        unsorted_regs = [
            {"title": "Reg C", "effective_on": "2025-03-15", "agencies": []},
            {"title": "Reg A", "effective_on": "2025-01-15", "agencies": []},
            {"title": "Reg B", "effective_on": "2025-02-15", "agencies": []}
        ]

        with patch.object(service, '_search_regulations', new_callable=AsyncMock) as mock_search:
            mock_search.return_value = unsorted_regs
            with patch.object(service, '_format_results') as mock_format:
                mock_format.return_value = "formatted"

                await service._get_regulations_impl(mock_client, ["term1"])

                sorted_regs = mock_format.call_args[0][0]
                dates = [r["effective_on"] for r in sorted_regs]
                assert dates == ["2025-01-15", "2025-02-15", "2025-03-15"]

    @pytest.mark.asyncio
    async def test_limits_to_8_regulations(self, service, mock_client):
        """Test _get_regulations_impl limits results to 8 regulations."""
        many_regs = [
            {"title": f"Reg {i}", "effective_on": f"2025-01-{i:02d}", "agencies": []}
            for i in range(1, 15)
        ]

        with patch.object(service, '_search_regulations', new_callable=AsyncMock) as mock_search:
            mock_search.return_value = many_regs
            with patch.object(service, '_format_results') as mock_format:
                mock_format.return_value = "formatted"

                await service._get_regulations_impl(mock_client, ["term1"])

                limited_regs = mock_format.call_args[0][0]
                assert len(limited_regs) == 8

    @pytest.mark.asyncio
    async def test_searches_first_3_terms(self, service, mock_client):
        """Test _get_regulations_impl only searches first 3 terms."""
        search_terms = ["term1", "term2", "term3", "term4", "term5"]

        with patch.object(service, '_search_regulations', new_callable=AsyncMock) as mock_search:
            mock_search.return_value = []
            with patch.object(service, '_format_results') as mock_format:
                mock_format.return_value = "formatted"

                await service._get_regulations_impl(mock_client, search_terms)

                # Should only call search 3 times
                assert mock_search.call_count == 3
                called_terms = [call[0][1] for call in mock_search.call_args_list]
                assert called_terms == ["term1", "term2", "term3"]


class TestFormatResults:
    def test_with_agencies(self, service, sample_regulation):
        """Test _format_results formats agencies correctly."""
        result = service._format_results([sample_regulation])

        assert result is not None
        assert "Test Agency" in result

    def test_with_long_abstract_truncated(self, service):
        """Test _format_results truncates abstracts longer than 500 characters."""
        long_abstract = "A" * 250 + "B" * 350  # 600 chars, B starts at 250
        regulation = {
            "title": "Test Regulation",
            "type": "Rule",
            "agencies": [{"name": "Test Agency"}],
            "publication_date": "2025-01-15",
            "effective_on": "2025-02-15",
            "abstract": long_abstract
        }

        result = service._format_results([regulation])

        assert result is not None
        assert "..." in result
        # The full 600-char abstract should not appear
        assert long_abstract not in result

    def test_empty_list_returns_none(self, service):
        """Test _format_results returns None for empty list."""
        result = service._format_results([])

        assert result is None

    def test_final_rule_type(self, service, sample_regulation):
        """Test _format_results converts RULE to Final Rule."""
        result = service._format_results([sample_regulation])

        assert result is not None
        assert "Final Rule" in result

    def test_proposed_rule_type(self, service, sample_proposed_regulation):
        """Test _format_results converts PRORULE to Proposed Rule."""
        result = service._format_results([sample_proposed_regulation])

        assert result is not None
        assert "Proposed Rule" in result

    def test_multiple_agencies(self, service):
        """Test _format_results handles multiple agencies."""
        regulation = {
            "title": "Test Regulation",
            "type": "Rule",
            "agencies": [
                {"name": "Agency One"},
                {"name": "Agency Two"}
            ],
            "publication_date": "2025-01-15",
            "effective_on": "2025-02-15",
            "abstract": "Test abstract"
        }

        result = service._format_results([regulation])

        assert result is not None
        assert "Agency One" in result
        assert "Agency Two" in result

    def test_missing_effective_date(self, service, sample_proposed_regulation):
        """Test _format_results handles missing effective_on date."""
        result = service._format_results([sample_proposed_regulation])

        assert result is not None
        # Should handle None effective_on gracefully


class TestSICCodeLookup:
    @pytest.mark.asyncio
    async def test_known_sic_prefix(self, service, mock_client):
        """Test that known SIC code prefix maps to correct topics."""
        with patch.object(service, '_get_regulations_impl', new_callable=AsyncMock) as mock_impl:
            mock_impl.return_value = "mocked results"

            # Test with SIC code 7372 (prepackaged software)
            await service.get_upcoming_regulations(
                company_name="Software Company",
                sic_code="7372",
                client=mock_client
            )

            call_args = mock_impl.call_args[0]
            search_terms = call_args[1]

            # Should map to software/technology related terms
            assert isinstance(search_terms, list)
            assert len(search_terms) > 0

    @pytest.mark.asyncio
    async def test_unknown_prefix_uses_default_topics(self, service, mock_client):
        """Test that unknown SIC code prefix uses DEFAULT_TOPICS."""
        with patch.object(service, '_get_regulations_impl', new_callable=AsyncMock) as mock_impl:
            mock_impl.return_value = "mocked results"

            # Test with unknown SIC code prefix
            await service.get_upcoming_regulations(
                company_name="Mystery Company",
                sic_code="9999",
                client=mock_client
            )

            call_args = mock_impl.call_args[0]
            search_terms = call_args[1]

            # Should use DEFAULT_TOPICS
            assert "data privacy" in search_terms or "cybersecurity regulation" in search_terms

    @pytest.mark.asyncio
    async def test_partial_sic_code(self, service, mock_client):
        """Test that partial SIC codes (less than 2 digits) are handled."""
        with patch.object(service, '_get_regulations_impl', new_callable=AsyncMock) as mock_impl:
            mock_impl.return_value = "mocked results"

            # Test with single digit SIC code
            await service.get_upcoming_regulations(
                company_name="Test Company",
                sic_code="7",
                client=mock_client
            )

            # Should not raise an error
            assert mock_impl.called
