"""test_claude.py - Tests for ClaudeService."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime

from services.claude import ClaudeService, ResearchValidationResult
from models import (
    ScrapedContent, TechStack, DetectedTechnology, ResearchDocument, PainInference,
    _classify_domain, format_multi_domain_tech, format_tech_by_tier,
)


@pytest.fixture
def claude_service():
    """Create a ClaudeService instance with mocked settings and client."""
    with patch("services.claude.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(
            openrouter_api_key="test-key",
            research_model="google/gemini-2.5-flash",
            research_tight_writing_enabled=False,
            research_tiered_prompt_enabled=False,
            research_validation_enabled=False,
        )
        with patch("services.claude.AsyncOpenAI"):
            service = ClaudeService()
            return service


@pytest.fixture
def tight_writing_service():
    """ClaudeService with research_tight_writing_enabled=True."""
    with patch("services.claude.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(
            openrouter_api_key="test-key",
            research_model="google/gemini-2.5-flash",
            research_tight_writing_enabled=True,
            research_tiered_prompt_enabled=False,
            research_validation_enabled=False,
        )
        with patch("services.claude.AsyncOpenAI"):
            service = ClaudeService()
            return service


@pytest.fixture
def tiered_service():
    """ClaudeService with research_tiered_prompt_enabled=True."""
    with patch("services.claude.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(
            openrouter_api_key="test-key",
            research_model="google/gemini-2.5-flash",
            research_tight_writing_enabled=False,
            research_tiered_prompt_enabled=True,
            research_validation_enabled=False,
        )
        with patch("services.claude.AsyncOpenAI"):
            service = ClaudeService()
            return service


@pytest.fixture
def validation_service():
    """ClaudeService with research_validation_enabled=True."""
    with patch("services.claude.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(
            openrouter_api_key="test-key",
            research_model="google/gemini-2.5-flash",
            research_tight_writing_enabled=False,
            research_tiered_prompt_enabled=False,
            research_validation_enabled=True,
        )
        with patch("services.claude.AsyncOpenAI"):
            service = ClaudeService()
            return service


class TestBuildSystemPrompt:
    """Tests for _build_system_prompt method."""

    def test_base_case_minimal(self, claude_service):
        """Test base prompt with only product_context."""
        result = claude_service._build_system_prompt(
            product_context="We sell database software."
        )

        assert "We sell database software." in result
        assert "YOUR PRODUCT CONTEXT" in result
        assert "OUTPUT FORMAT:" in result
        assert "OPPORTUNITY SCORING:" in result
        # Should not have seller company section
        assert "BACKGROUND KNOWLEDGE ABOUT" not in result
        # Should have no materials note
        assert "No sales materials have been uploaded yet" in result
        # Should not have ICP section
        assert "IDEAL CUSTOMER PROFILE:" not in result

    def test_with_seller_company(self, claude_service):
        """Test prompt with seller_company adds background knowledge section."""
        result = claude_service._build_system_prompt(
            product_context="Database software",
            seller_company="Acme Corp"
        )

        assert "BACKGROUND KNOWLEDGE ABOUT ACME CORP:" in result
        assert "Identifying competitors in the prospect's tech stack" in result
        assert "competes with Acme Corp" in result

    def test_with_retrieved_materials(self, claude_service):
        """Test prompt with materials adds materials section."""
        result = claude_service._build_system_prompt(
            product_context="Database software",
            retrieved_materials="Case study: Customer X reduced latency by 50%."
        )

        assert "YOUR SALES MATERIALS (PRIMARY SOURCE FOR PRODUCT DETAILS):" in result
        assert "Case study: Customer X reduced latency by 50%." in result
        assert "No sales materials have been uploaded yet" not in result

    def test_without_materials(self, claude_service):
        """Test prompt without materials shows note about uploading."""
        result = claude_service._build_system_prompt(
            product_context="Database software",
            retrieved_materials=""
        )

        assert "No sales materials have been uploaded yet" in result
        assert "YOUR SALES MATERIALS" not in result

    def test_with_target_industries(self, claude_service):
        """Test prompt with target_industries adds ICP section."""
        result = claude_service._build_system_prompt(
            product_context="Database software",
            target_industries="Fintech, Healthcare"
        )

        assert "IDEAL CUSTOMER PROFILE:" in result
        assert "Buyer company verticals" in result
        assert "Fintech, Healthcare" in result

    def test_with_target_personas(self, claude_service):
        """Test prompt with target_personas adds ICP and persona-aware sections."""
        result = claude_service._build_system_prompt(
            product_context="Database software",
            target_personas="CTO, VP Engineering"
        )

        assert "IDEAL CUSTOMER PROFILE:" in result
        assert "Persona emphasis" in result
        assert "CTO, VP Engineering" in result
        assert "PERSONA-AWARE DIRECTIVES" in result
        assert "Hooks" in result
        assert "Trap-Setting Questions" in result
        assert "Conversation Starters" in result

    def test_with_problems_solved(self, claude_service):
        """Test prompt with problems_solved adds ICP section."""
        result = claude_service._build_system_prompt(
            product_context="Database software",
            problems_solved="Slow queries, scaling challenges"
        )

        assert "IDEAL CUSTOMER PROFILE:" in result
        assert "Problem alignment" in result
        assert "Slow queries, scaling challenges" in result

    def test_with_multiple_icp_fields(self, claude_service):
        """Test prompt with multiple ICP fields combines them."""
        result = claude_service._build_system_prompt(
            product_context="Database software",
            target_industries="Fintech",
            target_personas="CTO",
            problems_solved="Database scaling"
        )

        assert "IDEAL CUSTOMER PROFILE:" in result
        assert "Buyer company verticals" in result
        assert "Persona emphasis" in result
        assert "Problem alignment" in result
        assert "Fintech" in result
        assert "CTO" in result
        assert "Database scaling" in result

    def test_horizontal_motion_light_boost(self, claude_service):
        """Horizontal motion gives light Fit boost, no hard penalty for non-matching verticals."""
        result = claude_service._build_system_prompt(
            product_context="Database software",
            target_industries="Financial Services, Healthcare",
            solution_motion="horizontal"
        )

        assert "Horizontal motion" in result
        assert "light Fit boost" in result
        assert "do not hard-penalize" in result

    def test_vertical_motion_strong_weighting(self, claude_service):
        """Vertical motion weights verticals heavily and penalizes non-matches."""
        result = claude_service._build_system_prompt(
            product_context="IT support services",
            target_industries="Healthcare, Insurance",
            solution_motion="vertical"
        )

        assert "Vertical motion" in result
        assert "weighted heavily" in result
        assert "meaningful Fit penalty" in result

    def test_seller_product_category_in_prompt(self, claude_service):
        """Seller product category appears in ICP section separately from buyer verticals."""
        result = claude_service._build_system_prompt(
            product_context="Compliance platform",
            target_industries="Healthcare",
            seller_product_category="HealthTech",
        )

        assert "Seller product category" in result
        assert "HealthTech" in result
        assert "do NOT use it to filter or score buyer accounts" in result

    def test_saas_vertical_no_msp_modifier(self, claude_service):
        """product_type='saas' + solution_motion='vertical' does NOT trigger MSP modifier."""
        result = claude_service._build_system_prompt(
            product_context="Healthcare compliance SaaS",
            target_industries="Healthcare",
            product_type="saas",
            solution_motion="vertical"
        )

        assert "Vertical motion" in result
        assert "PROFESSIONAL SERVICES / CONSULTANCY MODIFIER" not in result

    def test_msp_horizontal_gets_msp_modifier(self, claude_service):
        """product_type='msp' + solution_motion='horizontal' still gets MSP modifier."""
        result = claude_service._build_system_prompt(
            product_context="Managed IT services",
            target_industries="Healthcare, Financial Services",
            product_type="msp",
            solution_motion="horizontal"
        )

        assert "Horizontal motion" in result
        assert "PROFESSIONAL SERVICES / CONSULTANCY MODIFIER" in result

    def test_product_type_msp(self, claude_service):
        """Test prompt with product_type='msp' adds professional services modifier section."""
        result = claude_service._build_system_prompt(
            product_context="IT support services",
            product_type="msp"
        )

        assert "PROFESSIONAL SERVICES / CONSULTANCY MODIFIER" in result
        assert "professional services firm" in result
        assert "Absence of specialist hiring" in result

    def test_product_type_saas(self, claude_service):
        """Test prompt with product_type='saas' does not add MSP section."""
        result = claude_service._build_system_prompt(
            product_context="Database software",
            product_type="saas"
        )

        assert "PROFESSIONAL SERVICES / CONSULTANCY MODIFIER" not in result

    def test_all_parameters_combined(self, claude_service):
        """Test prompt with all parameters combined."""
        result = claude_service._build_system_prompt(
            product_context="Database software",
            retrieved_materials="Case study X",
            seller_company="Acme Corp",
            target_personas="CTO",
            target_industries="Fintech",
            problems_solved="Scaling",
            product_type="msp"
        )

        assert "Database software" in result
        assert "Case study X" in result
        assert "BACKGROUND KNOWLEDGE ABOUT ACME CORP:" in result
        assert "IDEAL CUSTOMER PROFILE:" in result
        assert "CTO" in result
        assert "Fintech" in result
        assert "Scaling" in result
        assert "PROFESSIONAL SERVICES / CONSULTANCY MODIFIER" in result
        assert "PERSONA-AWARE DIRECTIVES" in result


class TestBuildUserPrompt:
    """Tests for _build_user_prompt method."""

    def test_empty_scraped_content(self, claude_service):
        """Test with empty ScrapedContent produces minimal output."""
        scraped = ScrapedContent()
        result = claude_service._build_user_prompt(
            company_url="https://example.com",
            scraped=scraped
        )

        assert "# Research Data for https://example.com" in result
        assert "Please generate the Account Research Document" in result
        # Should not have any section headers for empty fields
        assert "## Homepage Content" not in result
        assert "## Site Structure" not in result

    def test_all_fields_populated(self, claude_service):
        """Test with all ScrapedContent fields populated."""
        scraped = ScrapedContent(
            homepage="Homepage content here",
            site_structure={
                "careers": "https://example.com/careers",
                "docs": "https://example.com/api/docs",
            },
            job_postings="Job posting 1\nJob posting 2",
            edgar_filings="SEC filing 1",
            federal_regulations="Regulation 1",
            firmographics="500 employees, Series B",
            web_mentions="Perplexity context",
        )
        result = claude_service._build_user_prompt(
            company_url="https://example.com",
            scraped=scraped
        )

        assert "## CONFIRMED Firmographic Data" in result
        assert "500 employees, Series B" in result
        assert "## Homepage Content" in result
        assert "Homepage content here" in result
        assert "## Site Structure" in result
        assert "Site structure: /careers, /api/docs" in result
        assert "## Detailed Job Postings" in result
        assert "Job posting 1" in result
        assert "## SEC EDGAR Filings (Public Company)" in result
        assert "SEC filing 1" in result
        assert "## Upcoming Federal Regulations" in result
        assert "Regulation 1" in result
        assert "## Third-Party Web Mentions" in result
        assert "Perplexity context" in result

    def test_tech_by_domain_included(self, claude_service):
        """Test with tech_by_domain adds verified technologies section."""
        scraped = ScrapedContent(homepage="Homepage")
        tech_by_domain = {
            "app.example.com": TechStack(
                technologies=[
                    DetectedTechnology(name="React", version="18.0", category="Framework")
                ]
            ),
            "www.example.com": TechStack(
                technologies=[
                    DetectedTechnology(name="WordPress", category="CMS")
                ]
            )
        }

        result = claude_service._build_user_prompt(
            company_url="https://example.com",
            scraped=scraped,
            tech_by_domain=tech_by_domain
        )

        assert "## VERIFIED Technologies (Detected by Scanning Website Code)" in result
        assert "Product/Application" in result
        assert "React 18.0" in result
        assert "Marketing Site" in result
        assert "WordPress" in result

    def test_truncation_homepage(self, claude_service):
        """Test that homepage is truncated to 5000 characters."""
        long_content = "x" * 10000
        scraped = ScrapedContent(homepage=long_content)

        result = claude_service._build_user_prompt(
            company_url="https://example.com",
            scraped=scraped
        )

        # Verify the truncated content is in the result
        assert "x" * 5000 in result
        # Verify it's not longer than 5000
        assert "x" * 5001 not in result

    def test_site_structure_formatting(self, claude_service):
        """Test that site structure is rendered as a compact path-only block."""
        scraped = ScrapedContent(
            site_structure={
                "careers": "https://example.com/careers/",
                "docs": "https://example.com/api/docs",
                "status": "https://example.com/status/",
            }
        )

        result = claude_service._build_user_prompt(
            company_url="https://example.com",
            scraped=scraped
        )

        assert "## Site Structure" in result
        assert "Site structure: /careers, /api/docs, /status" in result

    def test_truncation_job_postings(self, claude_service):
        """Test that job_postings is truncated to 15000 characters."""
        long_content = "z" * 20000
        scraped = ScrapedContent(job_postings=long_content)

        result = claude_service._build_user_prompt(
            company_url="https://example.com",
            scraped=scraped
        )

        assert "z" * 15000 in result
        assert "z" * 15001 not in result

    def test_section_ordering(self, claude_service):
        """Test that sections appear in the correct order."""
        scraped = ScrapedContent(
            firmographics="Firmographic data",
            homepage="Homepage",
            site_structure={"careers": "https://example.com/careers"},
            job_postings="Jobs"
        )

        result = claude_service._build_user_prompt(
            company_url="https://example.com",
            scraped=scraped
        )

        # Check order by finding indices
        firmographics_idx = result.index("## CONFIRMED Firmographic Data")
        homepage_idx = result.index("## Homepage Content")
        site_structure_idx = result.index("## Site Structure")
        jobs_idx = result.index("## Detailed Job Postings")

        assert firmographics_idx < homepage_idx < site_structure_idx < jobs_idx


class TestParseSections:
    """Tests for _parse_sections method."""

    def test_basic_sections(self, claude_service):
        """Test parsing basic sections with exact header matches."""
        markdown = """
## Company Overview
This is the overview.

## Confirmed Technology Stack
React, Node.js

## Technical Hiring Signals
5 open backend roles

## Stated Business Problems
Scaling challenges
"""

        result = claude_service._parse_sections(markdown)

        assert result["company_overview"] == "This is the overview."
        assert result["confirmed_tech_stack"] == "React, Node.js"
        assert result["hiring_signals"] == "5 open backend roles"
        assert result["business_problems"] == "Scaling challenges"

    def test_partial_header_matches(self, claude_service):
        """Test that partial matches work for specific headers."""
        markdown = """
## Product Fit Analysis
High fit based on signals.

## Recommended Talking Points
Talk about performance.

## Information Gaps
Missing contact data.
"""

        result = claude_service._parse_sections(markdown)

        assert result["product_fit"] == "High fit based on signals."
        assert result["talking_points"] == "Talk about performance."
        assert result["information_gaps"] == "Missing contact data."

    def test_alternative_header_names(self, claude_service):
        """Test alternative header names map correctly."""
        markdown = """
## Specific Projects and Initiatives
Project Alpha, Project Beta

## Hiring Signals
Rapid hiring

## Before Scenario
Problems identified
"""

        result = claude_service._parse_sections(markdown)

        assert result["projects_initiatives"] == "Project Alpha, Project Beta"
        assert result["hiring_signals"] == "Rapid hiring"
        assert result["before_scenario"] == "Problems identified"

    def test_unknown_headers_ignored(self, claude_service):
        """Test that unknown headers are ignored."""
        markdown = """
## Company Overview
Overview text

## Unknown Section
This should be ignored

## Confirmed Technology Stack
Tech stack info
"""

        result = claude_service._parse_sections(markdown)

        assert "company_overview" in result
        assert "confirmed_tech_stack" in result
        # Unknown section should not be in result
        assert len([k for k in result.keys() if "unknown" in k.lower()]) == 0

    def test_empty_markdown(self, claude_service):
        """Test parsing empty markdown returns empty dict."""
        result = claude_service._parse_sections("")
        assert result == {}

    def test_no_sections(self, claude_service):
        """Test markdown with no ## headers returns empty dict."""
        markdown = "Just some text without headers."
        result = claude_service._parse_sections(markdown)
        assert result == {}

    def test_multiline_content(self, claude_service):
        """Test sections with multiline content."""
        markdown = """
## Company Overview
Line 1
Line 2
Line 3

## Confirmed Technology Stack
Tech 1
Tech 2
"""

        result = claude_service._parse_sections(markdown)

        assert "Line 1\nLine 2\nLine 3" in result["company_overview"]
        assert "Tech 1\nTech 2" in result["confirmed_tech_stack"]

    def test_case_insensitive_matching(self, claude_service):
        """Test that header matching is case-insensitive."""
        markdown = """
## COMPANY OVERVIEW
Uppercase header

## company overview
This should overwrite the previous one

## CoMpAnY OvErViEw
Mixed case
"""

        result = claude_service._parse_sections(markdown)

        # Last occurrence should win
        assert result["company_overview"] == "Mixed case"


class TestParseScores:
    """Tests for _parse_scores method."""

    def test_all_scores_present(self, claude_service):
        """Test parsing when all scores are present."""
        markdown = """
SCORE_PAIN: 75
SCORE_PAIN_EVIDENCE: - Signal 1
- Signal 2
SCORE_FIT: 85
SCORE_FIT_EVIDENCE: - Good ICP match
SCORE_TIMING: 60
SCORE_TIMING_EVIDENCE: - Recent funding
SCORE_COMPOSITE: 74
SCORE_SUMMARY: Strong opportunity based on pain and fit.
"""

        result = claude_service._parse_scores(markdown)

        assert result["pain"] == 75
        assert result["fit"] == 85
        assert result["timing"] == 60
        assert result["composite"] == 74
        assert result["summary"] == "Strong opportunity based on pain and fit."
        assert "Signal 1" in result["pain_evidence"]
        assert "Good ICP match" in result["fit_evidence"]
        assert "Recent funding" in result["timing_evidence"]

    def test_missing_composite_score_calculated(self, claude_service):
        """Test that composite score is calculated if missing."""
        markdown = """
SCORE_PAIN: 80
SCORE_FIT: 60
SCORE_TIMING: 50
"""

        result = claude_service._parse_scores(markdown)

        # Composite = pain*0.4 + fit*0.35 + timing*0.25
        # = 80*0.4 + 60*0.35 + 50*0.25
        # = 32 + 21 + 12.5 = 65.5 -> 66
        expected = round(80 * 0.4 + 60 * 0.35 + 50 * 0.25)
        assert result["composite"] == expected

    def test_score_clamping_high(self, claude_service):
        """Test that scores above 100 are clamped to 100."""
        markdown = """
SCORE_PAIN: 150
SCORE_FIT: 120
SCORE_TIMING: 200
SCORE_COMPOSITE: 180
"""

        result = claude_service._parse_scores(markdown)

        assert result["pain"] == 100
        assert result["fit"] == 100
        assert result["timing"] == 100
        assert result["composite"] == 100

    def test_score_clamping_low(self, claude_service):
        """Test that scores of 0 are handled correctly."""
        markdown = """
SCORE_PAIN: 0
SCORE_FIT: 0
SCORE_TIMING: 0
SCORE_COMPOSITE: 0
"""

        result = claude_service._parse_scores(markdown)

        assert result["pain"] == 0
        assert result["fit"] == 0
        assert result["timing"] == 0
        assert result["composite"] == 0

    def test_evidence_extraction_multiline(self, claude_service):
        """Test extraction of multiline evidence fields."""
        markdown = """
SCORE_PAIN: 70
SCORE_PAIN_EVIDENCE: - Database scaling issues mentioned in job posting
- 4 backend roles open for 3+ months
- PostgreSQL on app domain with growth signals
SCORE_FIT: 80
SCORE_FIT_EVIDENCE: - Fintech industry (target)
- 500 employees (sweet spot)
SCORE_TIMING: 65
SCORE_TIMING_EVIDENCE: - Series B announced 2 months ago
SCORE_COMPOSITE: 72
SCORE_SUMMARY: Good opportunity.
"""

        result = claude_service._parse_scores(markdown)

        assert "Database scaling issues" in result["pain_evidence"]
        assert "4 backend roles" in result["pain_evidence"]
        assert "PostgreSQL" in result["pain_evidence"]
        assert "Fintech industry" in result["fit_evidence"]
        assert "500 employees" in result["fit_evidence"]
        assert "Series B" in result["timing_evidence"]

    def test_no_scores_found(self, claude_service):
        """Test parsing markdown with no scores."""
        markdown = """
## Company Overview
Just some regular content.

## Talking Points
No scores here.
"""

        result = claude_service._parse_scores(markdown)

        assert result == {}

    def test_partial_scores(self, claude_service):
        """Test with only some scores present."""
        markdown = """
SCORE_PAIN: 50
SCORE_FIT: 60
"""

        result = claude_service._parse_scores(markdown)

        assert result["pain"] == 50
        assert result["fit"] == 60
        # No timing score, so no composite calculation
        assert "composite" not in result

    def test_summary_extraction(self, claude_service):
        """Test summary extraction with various formats."""
        markdown = """
SCORE_COMPOSITE: 70
SCORE_SUMMARY: Strong fit but limited timing signals.
"""

        result = claude_service._parse_scores(markdown)

        assert result["summary"] == "Strong fit but limited timing signals."


class TestExtractDomain:
    """Tests for _extract_domain method."""

    def test_https_url(self, claude_service):
        """Test extracting domain from https URL."""
        result = claude_service._extract_domain("https://example.com")
        assert result == "example.com"

    def test_http_url(self, claude_service):
        """Test extracting domain from http URL."""
        result = claude_service._extract_domain("http://example.com")
        assert result == "example.com"

    def test_url_with_path(self, claude_service):
        """Test extracting domain from URL with path."""
        result = claude_service._extract_domain("https://example.com/path/to/page")
        assert result == "example.com"

    def test_url_with_www(self, claude_service):
        """Test extracting domain strips www prefix."""
        result = claude_service._extract_domain("https://www.example.com")
        assert result == "example.com"

    def test_url_with_www_and_path(self, claude_service):
        """Test extracting domain strips www and path."""
        result = claude_service._extract_domain("https://www.example.com/about")
        assert result == "example.com"

    def test_subdomain(self, claude_service):
        """Test extracting domain with subdomain (keeps subdomain)."""
        result = claude_service._extract_domain("https://app.example.com")
        assert result == "app.example.com"

    def test_subdomain_with_www(self, claude_service):
        """Test subdomain with www is stripped."""
        result = claude_service._extract_domain("https://www.app.example.com")
        # This would become app.example.com after stripping www.
        assert result == "app.example.com"

    def test_no_protocol(self, claude_service):
        """Test domain without protocol."""
        result = claude_service._extract_domain("example.com")
        assert result == "example.com"

    def test_port_number(self, claude_service):
        """Test URL with port number."""
        result = claude_service._extract_domain("https://example.com:8080")
        assert result == "example.com:8080"


class TestGenerateResearchDocument:
    """Tests for generate_research_document method."""

    @pytest.mark.asyncio
    async def test_generate_research_document(self):
        """Test the full generate_research_document method with mocked API."""
        # Create a mock response (OpenAI SDK shape)
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = """## Company Overview
Acme Corp is a fintech startup.

## Specific Projects & Initiatives
None found.

## Confirmed Technology Stack
React, Node.js

## Technical Hiring Signals
5 backend engineers

## Stated Business Problems
Database performance

## Existential Data Points
None identified

## Product Fit Analysis
High fit

## Recommended Talking Points
Database optimization

## Key Contacts
Jane Doe, CTO

## Information Gaps
No technical blog

## Opportunity Score

SCORE_PAIN: 75
SCORE_PAIN_EVIDENCE: - Database performance issues
- Active hiring
SCORE_FIT: 85
SCORE_FIT_EVIDENCE: - Fintech industry
SCORE_TIMING: 60
SCORE_TIMING_EVIDENCE: - Recent funding
SCORE_COMPOSITE: 74
SCORE_SUMMARY: Strong opportunity.
"""

        # Create service with mocked client
        with patch("services.claude.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(openrouter_api_key="test-key", research_model="google/gemini-2.5-flash", research_tight_writing_enabled=False, research_tiered_prompt_enabled=False, research_validation_enabled=False)
            with patch("services.claude.AsyncOpenAI") as mock_openai:
                mock_client = AsyncMock()
                mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
                mock_openai.return_value = mock_client

                service = ClaudeService()

                # Create test data
                scraped = ScrapedContent(
                    homepage="Acme Corp homepage",
                    about="About Acme Corp"
                )

                # Call the method
                result = await service.generate_research_document(
                    company_url="https://acme.com",
                    scraped=scraped,
                    product_context="Database software"
                )

                # Verify the result
                assert isinstance(result, ResearchDocument)
                assert result.company_url == "https://acme.com"
                assert result.company_name == "acme.com"
                assert result.company_overview == "Acme Corp is a fintech startup."
                assert result.projects_initiatives == "None found."
                assert result.confirmed_tech_stack == "React, Node.js"
                assert result.hiring_signals == "5 backend engineers"
                assert result.business_problems == "Database performance"
                assert result.product_fit == "High fit"
                assert result.talking_points == "Database optimization"
                assert result.recent_news == ""
                assert result.key_contacts == "Jane Doe, CTO"
                assert result.information_gaps == "No technical blog"

                # Check scores
                assert result.pain_score == 75
                assert result.fit_score == 85
                assert result.timing_score == 60
                assert result.opportunity_score == 74
                assert result.score_summary == "Strong opportunity."
                assert "Database performance issues" in result.pain_evidence
                assert "Fintech industry" in result.fit_evidence
                assert "Recent funding" in result.timing_evidence

                # Check metadata
                assert result.thinking_content is None or result.thinking_content == ""
                assert result.model_used == "google/gemini-2.5-flash"
                assert isinstance(result.created_at, datetime)

                # Verify API was called correctly
                mock_client.chat.completions.create.assert_called_once()
                call_kwargs = mock_client.chat.completions.create.call_args[1]
                assert call_kwargs["model"] == "google/gemini-2.5-flash"
                assert call_kwargs["max_tokens"] == 16000
                assert call_kwargs["temperature"] == 1.0
                # System prompt is now in messages array
                assert call_kwargs["messages"][0]["role"] == "system"
                assert "Database software" in call_kwargs["messages"][0]["content"]
                assert "acme.com" in call_kwargs["messages"][1]["content"]

    @pytest.mark.asyncio
    async def test_generate_research_document_with_all_parameters(self):
        """Test generate_research_document with all optional parameters."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = """## Company Overview
Test company

## Opportunity Score
SCORE_PAIN: 50
SCORE_FIT: 60
SCORE_TIMING: 40
SCORE_COMPOSITE: 51
SCORE_SUMMARY: Medium opportunity
"""

        with patch("services.claude.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(openrouter_api_key="test-key", research_model="google/gemini-2.5-flash", research_tight_writing_enabled=False, research_tiered_prompt_enabled=False, research_validation_enabled=False)
            with patch("services.claude.AsyncOpenAI") as mock_openai:
                mock_client = AsyncMock()
                mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
                mock_openai.return_value = mock_client

                service = ClaudeService()

                scraped = ScrapedContent(homepage="Test")
                tech_by_domain = {
                    "app.test.com": TechStack(
                        technologies=[DetectedTechnology(name="React")]
                    )
                }

                result = await service.generate_research_document(
                    company_url="https://test.com",
                    scraped=scraped,
                    product_context="Database",
                    tech_by_domain=tech_by_domain,
                    retrieved_materials="Case study 1",
                    seller_company="Seller Co",
                    target_personas="CTO",
                    target_industries="Fintech",
                    problems_solved="Scaling",
                    product_type="msp"
                )

                # Verify all parameters were passed to system prompt
                call_kwargs = mock_client.chat.completions.create.call_args[1]
                system_prompt = call_kwargs["messages"][0]["content"]
                assert "Database" in system_prompt
                assert "Case study 1" in system_prompt
                assert "Seller Co" in system_prompt
                assert "CTO" in system_prompt
                assert "Financial Services" in system_prompt
                assert "Scaling" in system_prompt
                assert "PROFESSIONAL SERVICES / CONSULTANCY MODIFIER" in system_prompt

                # Verify tech stack in user prompt
                user_prompt = call_kwargs["messages"][1]["content"]
                assert "VERIFIED Technologies" in user_prompt
                assert "React" in user_prompt


class TestTightWritingStyleContract:
    """Tests for style contract injection controlled by feature flag."""

    def test_flag_off_no_style_contract(self, claude_service):
        """When flag is off, STYLE CONTRACT is absent from prompt."""
        result = claude_service._build_system_prompt(product_context="Database software")
        assert "STYLE CONTRACT" not in result

    def test_flag_off_no_banned_phrases_list(self, claude_service):
        """When flag is off, banned phrases list is absent."""
        result = claude_service._build_system_prompt(product_context="Database software")
        assert "Banned hedge phrases" not in result

    def test_flag_off_no_word_limits(self, claude_service):
        """When flag is off, section word-limit annotations are absent."""
        result = claude_service._build_system_prompt(product_context="Database software")
        assert "(60-90 words total.)" not in result
        assert "(80-120 words per data point.)" not in result

    def test_flag_on_style_contract_present(self, tight_writing_service):
        """When flag is on, STYLE CONTRACT block is injected."""
        result = tight_writing_service._build_system_prompt(product_context="Database software")
        assert "STYLE CONTRACT" in result
        assert "Banned hedge phrases" in result
        assert "it appears" in result
        assert "60-90 words" in result

    def test_flag_on_output_format_and_scoring_preserved(self, tight_writing_service):
        """Enabling tight writing does not remove OUTPUT FORMAT or OPPORTUNITY SCORING."""
        result = tight_writing_service._build_system_prompt(product_context="Database software")
        assert "OUTPUT FORMAT:" in result
        assert "OPPORTUNITY SCORING:" in result


class TestFormatSections:
    """Tests for post-generation formatter methods."""

    def test_strips_banned_hedge_phrases(self, tight_writing_service):
        """Banned hedge phrases are removed, real content preserved."""
        sections = {
            "company_overview": "It appears the company is growing. They have 500 employees.",
            "business_problems": "It is worth noting that scaling is hard.",
        }
        result = tight_writing_service._format_sections(sections)
        assert "It appears" not in result["company_overview"]
        assert "500 employees" in result["company_overview"]
        assert "It is worth noting" not in result["business_problems"]
        assert "scaling is hard" in result["business_problems"]

    def test_normalizes_bullet_styles(self, tight_writing_service):
        """*, bullet, and en-dash bullets all become '- '."""
        sections = {
            "talking_points": "* First point\n• Second point\n– Third point\n- Already correct",
        }
        result = tight_writing_service._format_sections(sections)
        lines = result["talking_points"].split("\n")
        assert all(line.startswith("- ") for line in lines if line.strip())

    def test_dedup_removes_from_lower_priority(self, tight_writing_service):
        """Duplicate line in existential + business_problems → removed from business_problems only."""
        duplicate_line = "PostgreSQL on app domain with 3x user growth signals performance risk."
        sections = {
            "existential_data_points": f"- {duplicate_line}",
            "business_problems": f"- {duplicate_line}\n- Unique business problem here noted.",
        }
        result = tight_writing_service._format_sections(sections)
        assert duplicate_line in result["existential_data_points"]
        assert duplicate_line not in result["business_problems"]
        assert "Unique business problem" in result["business_problems"]

    def test_fail_open_returns_original_on_error(self, tight_writing_service):
        """If a sub-method raises, _format_sections returns original sections unchanged."""
        sections = {"company_overview": "Test content."}
        with patch.object(tight_writing_service, "_strip_hedge_phrases", side_effect=RuntimeError("boom")):
            result = tight_writing_service._format_sections(sections)
        assert result == sections

    def test_unmodified_sections_pass_through(self, tight_writing_service):
        """Sections without hedges, odd bullets, or duplicates pass through unchanged."""
        sections = {
            "company_overview": "Acme Corp builds enterprise software for fintech.",
            "confirmed_tech_stack": "- React\n- Node.js\n- PostgreSQL",
        }
        result = tight_writing_service._format_sections(sections)
        assert result["company_overview"] == "Acme Corp builds enterprise software for fintech."
        assert result["confirmed_tech_stack"] == "- React\n- Node.js\n- PostgreSQL"

    def test_strip_hedges_does_not_corrupt_words_with_substring_match(self, tight_writing_service):
        """'overall' should not mutate words like 'Overallocation'."""
        sections = {
            "business_problems": "Overallocation risk may indicate capacity strain in peak windows.",
        }
        result = tight_writing_service._format_sections(sections)
        assert "Overallocation" in result["business_problems"]

    def test_strip_hedges_keeps_mid_sentence_uncertainty_language(self, tight_writing_service):
        """Mid-sentence 'may indicate' should not be stripped."""
        sections = {
            "business_problems": "Their job mix may indicate platform modernization pressure.",
        }
        result = tight_writing_service._format_sections(sections)
        assert "may indicate" in result["business_problems"].lower()

    def test_strip_hedges_removes_sentence_leading_phrase(self, tight_writing_service):
        """Sentence-leading hedge phrase should be removed cleanly."""
        sections = {
            "company_overview": "In summary, the team is expanding in EMEA.",
        }
        result = tight_writing_service._format_sections(sections)
        assert "In summary" not in result["company_overview"]
        assert result["company_overview"].startswith("the team is expanding")


# --- Frontend signal suppression in system prompt ---


class TestFrontendSignalSuppression:
    def test_suppression_handled_by_pipeline(self, claude_service):
        """Frontend/CDN/security suppression is now handled upstream by the pipeline.

        Tech detection scopes to product domains only (no marketing site),
        and pain_inference handles seller-category boosting/dampening.
        The system prompt no longer contains suppression instructions.
        """
        result = claude_service._build_system_prompt(
            product_context="MongoDB Atlas - scalable nosql database platform",
            problems_solved="database scaling, sql query performance",
            seller_product_category="database",
        )
        assert "FRONTEND/CDN SIGNAL SUPPRESSION" not in result
        assert "SECURITY SIGNAL SUPPRESSION" not in result
        assert "WEBSITE QUALITY SIGNAL SUPPRESSION" not in result


# --- Background-only pain signal rendering ---


class TestBackgroundOnlyPainSignals:
    def test_background_signals_separated_in_user_prompt(self, claude_service):
        """Background-tagged inferences render under 'Background-Only Signals' header."""
        scraped = ScrapedContent(homepage="Test homepage content.")
        pain_inferences = [
            PainInference(
                rule_id="database_scaling_pressure",
                title="Database Scaling Pressure",
                description="Single DB with hiring.",
                severity="medium",
                evidence=["Single database: postgresql"],
                confidence=55,
                category="engineering",
            ),
            PainInference(
                rule_id="frontend_performance_debt",
                title="Frontend Performance Debt",
                description="Multiple JS frameworks without CDN.",
                severity="medium",
                evidence=["Frameworks: React, Vue"],
                confidence=50,
                category="_background_engineering",
            ),
        ]
        result = claude_service._build_user_prompt(
            "https://example.com", scraped, pain_inferences=pain_inferences,
        )
        assert "## Programmatic Pain Signals" in result
        assert "Database Scaling Pressure" in result
        assert "## Background-Only Signals (DO NOT use in Action Tier)" in result
        assert "Frontend Performance Debt" in result

    def test_no_background_signals_no_background_section(self, claude_service):
        """When all inferences are action-tier, no background section appears."""
        scraped = ScrapedContent(homepage="Test homepage content.")
        pain_inferences = [
            PainInference(
                rule_id="database_scaling_pressure",
                title="Database Scaling Pressure",
                description="Single DB with hiring.",
                severity="medium",
                evidence=["Single database: postgresql"],
                confidence=55,
                category="engineering",
            ),
        ]
        result = claude_service._build_user_prompt(
            "https://example.com", scraped, pain_inferences=pain_inferences,
        )
        assert "## Programmatic Pain Signals" in result
        assert "Background-Only Signals" not in result

    def test_all_background_no_action_tier_section(self, claude_service):
        """When all inferences are background-only, no action-tier pain signal section appears."""
        scraped = ScrapedContent(homepage="Test homepage content.")
        pain_inferences = [
            PainInference(
                rule_id="frontend_performance_debt",
                title="Frontend Performance Debt",
                description="Multiple JS frameworks without CDN.",
                severity="medium",
                evidence=["Frameworks: React, Vue"],
                confidence=50,
                category="_background_engineering",
            ),
        ]
        result = claude_service._build_user_prompt(
            "https://example.com", scraped, pain_inferences=pain_inferences,
        )
        assert "## Programmatic Pain Signals" not in result
        assert "## Background-Only Signals (DO NOT use in Action Tier)" in result

    def test_background_signal_shows_real_category(self, claude_service):
        """Background signal renders its real category (without prefix) in output."""
        scraped = ScrapedContent(homepage="Test homepage content.")
        pain_inferences = [
            PainInference(
                rule_id="frontend_performance_debt",
                title="Frontend Performance Debt",
                description="Multiple JS frameworks without CDN.",
                severity="medium",
                evidence=["Frameworks: React, Vue"],
                confidence=50,
                category="_background_engineering",
            ),
        ]
        result = claude_service._build_user_prompt(
            "https://example.com", scraped, pain_inferences=pain_inferences,
        )
        assert "[engineering]" in result
        assert "_background_" not in result.split("Background-Only Signals")[1]


class TestFormatJobSignalsSection:
    """Tests for _format_job_signals_section static method."""

    def _make_signals(self, role_types=None, tech_mentions=None, seniority=None):
        from models import JobSignals, TechMention
        return JobSignals(
            tech_mentions=tech_mentions or [],
            role_types=role_types or [],
            seniority_distribution=seniority or {},
            total_roles_parsed=0,
        )

    def test_known_category_splits_relevant_and_other(self):
        signals = self._make_signals(role_types=["marketing", "sales", "backend", "frontend"])
        lines = ClaudeService._format_job_signals_section(signals, "MarTech")
        joined = "\n".join(lines)
        assert "Relevant role types (MarTech seller): marketing, sales" in joined
        assert "Other role types: backend, frontend" in joined

    def test_unknown_category_falls_back_to_single_line(self):
        signals = self._make_signals(role_types=["backend", "marketing"])
        lines = ClaudeService._format_job_signals_section(signals, "SomeUnknown")
        joined = "\n".join(lines)
        assert "- Role types: backend, marketing" in joined
        assert "Relevant" not in joined

    def test_empty_category_falls_back_to_single_line(self):
        signals = self._make_signals(role_types=["backend"])
        lines = ClaudeService._format_job_signals_section(signals, "")
        joined = "\n".join(lines)
        assert "- Role types: backend" in joined
        assert "Relevant" not in joined

    def test_no_roles_omits_role_lines(self):
        from models import TechMention
        signals = self._make_signals(
            tech_mentions=[TechMention(name="Python", category="language", count=1)],
        )
        lines = ClaudeService._format_job_signals_section(signals, "MarTech")
        joined = "\n".join(lines)
        assert "Role types" not in joined
        assert "language: Python" in joined

    def test_all_roles_relevant_no_other_line(self):
        signals = self._make_signals(role_types=["marketing", "sales"])
        lines = ClaudeService._format_job_signals_section(signals, "MarTech")
        joined = "\n".join(lines)
        assert "Relevant role types" in joined
        assert "Other role types" not in joined

    def test_no_roles_relevant_only_other_line(self):
        signals = self._make_signals(role_types=["backend", "frontend"])
        lines = ClaudeService._format_job_signals_section(signals, "HealthTech")
        joined = "\n".join(lines)
        assert "Other role types: backend, frontend" in joined
        assert "Relevant role types" not in joined

    def test_construction_tech_project_management_relevant(self):
        signals = self._make_signals(role_types=["project_management", "backend"])
        lines = ClaudeService._format_job_signals_section(signals, "ConstructionTech")
        joined = "\n".join(lines)
        assert "Relevant role types (ConstructionTech seller): project_management" in joined
        assert "Other role types: backend" in joined

    def test_seniority_included(self):
        signals = self._make_signals(seniority={"senior": 3, "junior": 1})
        lines = ClaudeService._format_job_signals_section(signals, "")
        joined = "\n".join(lines)
        assert "Seniority: senior: 3, junior: 1" in joined


# --- Format Tech By Tier ---


class TestFormatTechByTier:
    """Tests for _classify_domain and format_tech_by_tier."""

    def test_classify_product_domains(self):
        """Product/Application subdomains are classified correctly."""
        for prefix in ("app.", "dashboard.", "portal.", "console.", "platform.", "my.", "admin.", "web."):
            assert _classify_domain(f"{prefix}example.com") == "Product/Application"

    def test_classify_api_domain(self):
        assert _classify_domain("api.example.com") == "API"

    def test_classify_marketing_site(self):
        assert _classify_domain("example.com") == "Marketing Site"
        assert _classify_domain("www.example.com") == "Marketing Site"

    def test_classify_case_insensitive(self):
        """Mixed case should still classify correctly."""
        assert _classify_domain("App.Example.com") == "Product/Application"
        assert _classify_domain("API.Example.com") == "API"

    def test_classify_www_prefix_stripped(self):
        """www. prefix is stripped before classification."""
        assert _classify_domain("www.app.example.com") == "Product/Application"
        assert _classify_domain("www.api.example.com") == "API"

    def test_format_multi_domain_tech_uses_classify_domain(self):
        """format_multi_domain_tech produces same buckets as _classify_domain."""
        tech_by_domain = {
            "app.example.com": TechStack(technologies=[DetectedTechnology(name="React")]),
            "example.com": TechStack(technologies=[DetectedTechnology(name="WordPress")]),
        }
        result = format_multi_domain_tech(tech_by_domain)
        assert "Product/Application" in result
        assert "Marketing Site" in result

    def test_format_tech_by_tier_splits_correctly(self):
        """Product/API goes to tier1, marketing to tier3."""
        tech_by_domain = {
            "app.example.com": TechStack(technologies=[DetectedTechnology(name="React")]),
            "api.example.com": TechStack(technologies=[DetectedTechnology(name="FastAPI")]),
            "example.com": TechStack(technologies=[DetectedTechnology(name="WordPress")]),
        }
        tier1, tier3 = format_tech_by_tier(tech_by_domain)
        assert "React" in tier1
        assert "FastAPI" in tier1
        assert "WordPress" in tier3
        assert "WordPress" not in tier1
        assert "React" not in tier3

    def test_format_tech_by_tier_empty_input(self):
        tier1, tier3 = format_tech_by_tier({})
        assert tier1 == ""
        assert tier3 == ""

    def test_format_tech_by_tier_only_product(self):
        """Only product tech → tier1 populated, tier3 empty."""
        tech_by_domain = {
            "app.example.com": TechStack(technologies=[DetectedTechnology(name="React")]),
        }
        tier1, tier3 = format_tech_by_tier(tech_by_domain)
        assert "React" in tier1
        assert tier3 == ""

    def test_format_tech_by_tier_only_marketing(self):
        """Only marketing tech → tier3 populated, tier1 empty."""
        tech_by_domain = {
            "example.com": TechStack(technologies=[DetectedTechnology(name="WordPress")]),
        }
        tier1, tier3 = format_tech_by_tier(tech_by_domain)
        assert tier1 == ""
        assert "WordPress" in tier3

    def test_format_tech_by_tier_skips_empty_stacks(self):
        """Domains with no technologies are skipped."""
        tech_by_domain = {
            "app.example.com": TechStack(technologies=[]),
            "example.com": TechStack(technologies=[DetectedTechnology(name="WordPress")]),
        }
        tier1, tier3 = format_tech_by_tier(tech_by_domain)
        assert tier1 == ""
        assert "WordPress" in tier3


# --- Tiered User Prompt ---


class TestTieredUserPrompt:
    """Tests for _build_tiered_user_prompt and the dispatch logic."""

    def test_flag_off_uses_flat_prompt(self, claude_service):
        """When tiered flag is off, _build_user_prompt uses flat format."""
        scraped = ScrapedContent(homepage="Test")
        result = claude_service._build_user_prompt("https://example.com", scraped)
        assert "## TIER 1:" not in result
        assert "## Homepage Content" in result

    def test_flag_on_uses_tiered_prompt(self, tiered_service):
        """When tiered flag is on, _build_user_prompt uses tiered format."""
        scraped = ScrapedContent(homepage="Test")
        result = tiered_service._build_user_prompt("https://example.com", scraped)
        assert "## TIER 2: MEDIUM-CONFIDENCE SIGNALS" in result
        assert "## Homepage Content" in result

    def test_tier_headers_present_and_ordered(self, tiered_service):
        """All three tier headers appear in correct order when content exists."""
        scraped = ScrapedContent(
            homepage="Homepage", firmographics="500 employees",
            web_mentions="External context",
        )
        tech_by_domain = {
            "app.example.com": TechStack(technologies=[DetectedTechnology(name="React")]),
            "example.com": TechStack(technologies=[DetectedTechnology(name="WordPress")]),
        }
        result = tiered_service._build_user_prompt(
            "https://example.com", scraped, tech_by_domain=tech_by_domain,
        )
        t1 = result.index("## TIER 1: HIGH-CONFIDENCE SIGNALS")
        t2 = result.index("## TIER 2: MEDIUM-CONFIDENCE SIGNALS")
        t3 = result.index("## TIER 3: LOWER-CONFIDENCE SIGNALS")
        assert t1 < t2 < t3

    def test_site_structure_in_tier2(self, tiered_service):
        """Site structure should appear as a compact Tier 2 signal block."""
        scraped = ScrapedContent(
            homepage="Homepage",
            site_structure={
                "careers": "https://example.com/careers",
                "docs": "https://example.com/api/docs",
            },
        )
        result = tiered_service._build_user_prompt("https://example.com", scraped)
        t2_start = result.index("## TIER 2:")
        tier2 = result[t2_start:]
        assert "## Site Structure" in tier2
        assert "Site structure: /careers, /api/docs" in tier2

    def test_empty_tiers_suppressed(self, tiered_service):
        """Tiers with no content should not emit headers."""
        scraped = ScrapedContent(homepage="Just homepage")
        result = tiered_service._build_user_prompt("https://example.com", scraped)
        # No tech, no firmographics, no edgar → no tier1
        assert "## TIER 1:" not in result
        # Homepage exists → tier2 present
        assert "## TIER 2:" in result

    def test_product_tech_in_tier1_marketing_excluded(self, tiered_service):
        """Product/app tech goes to tier 1, marketing site tech is excluded."""
        scraped = ScrapedContent()
        tech_by_domain = {
            "app.example.com": TechStack(technologies=[DetectedTechnology(name="React")]),
            "example.com": TechStack(technologies=[DetectedTechnology(name="jQuery")]),
        }
        result = tiered_service._build_user_prompt(
            "https://example.com", scraped, tech_by_domain=tech_by_domain,
        )
        t1_start = result.index("## TIER 1:")
        tier1_section = result[t1_start:]
        assert "React" in tier1_section
        # Marketing site tech no longer included (Phase 2 stopped collecting it)
        assert "Marketing Site" not in result

    def test_pain_split_by_confidence(self, tiered_service):
        """Pain inferences are split into tiers by confidence."""
        scraped = ScrapedContent(homepage="Test", firmographics="500 employees")
        pains = [
            PainInference(rule_id="high", title="High Pain", description="Desc", severity="high",
                          evidence=["ev1"], confidence=80, category="engineering"),
            PainInference(rule_id="med", title="Med Pain", description="Desc", severity="medium",
                          evidence=["ev2"], confidence=55, category="operations"),
            PainInference(rule_id="low", title="Low Pain", description="Desc", severity="low",
                          evidence=["ev3"], confidence=20, category="marketing"),
            PainInference(rule_id="bg", title="BG Pain", description="Desc", severity="low",
                          evidence=["ev4"], confidence=50, category="_background_security"),
        ]
        result = tiered_service._build_user_prompt(
            "https://example.com", scraped, pain_inferences=pains,
        )
        t1_start = result.index("## TIER 1:")
        t2_start = result.index("## TIER 2:")
        t3_start = result.index("## TIER 3:")
        tier1 = result[t1_start:t2_start]
        tier2 = result[t2_start:t3_start]
        tier3 = result[t3_start:]
        assert "High Pain" in tier1
        assert "Med Pain" in tier2
        assert "Low Pain" in tier3
        assert "BG Pain" in tier3

    def test_edgar_in_tier1(self, tiered_service):
        """SEC EDGAR filings should appear in Tier 1."""
        scraped = ScrapedContent(edgar_filings="10-K filing content")
        result = tiered_service._build_user_prompt("https://example.com", scraped)
        assert "## TIER 1:" in result
        t1_start = result.index("## TIER 1:")
        # Find if tier 2 exists
        if "## TIER 2:" in result:
            t1_end = result.index("## TIER 2:")
        else:
            t1_end = len(result)
        tier1 = result[t1_start:t1_end]
        assert "SEC EDGAR Filings" in tier1

    def test_web_mentions_in_tier3(self, tiered_service):
        """Web mentions should appear in Tier 3."""
        scraped = ScrapedContent(homepage="Test", web_mentions="Crunchbase data")
        result = tiered_service._build_user_prompt("https://example.com", scraped)
        assert "## TIER 3:" in result
        t3_start = result.index("## TIER 3:")
        tier3 = result[t3_start:]
        assert "Third-Party Web Mentions" in tier3

    def test_job_postings_cap_12000(self, tiered_service):
        """Job postings are capped at 12000 chars in tiered mode."""
        scraped = ScrapedContent(job_postings="x" * 15000)
        result = tiered_service._build_user_prompt("https://example.com", scraped)
        assert "x" * 12000 in result
        assert "x" * 12001 not in result

    def test_marketing_tech_excluded_from_prompt(self, tiered_service):
        """Marketing-site tech is no longer included in the tiered prompt."""
        many_techs = [DetectedTechnology(name=f"Tech{i}", category="Framework") for i in range(200)]
        tech_by_domain = {
            "example.com": TechStack(technologies=many_techs),
        }
        scraped = ScrapedContent()
        result = tiered_service._build_user_prompt(
            "https://example.com", scraped, tech_by_domain=tech_by_domain,
        )
        assert "Marketing Site" not in result

    def test_system_prompt_includes_tier_structure_when_enabled(self, tiered_service):
        """System prompt includes EVIDENCE HIERARCHY when flag is on."""
        result = tiered_service._build_system_prompt(product_context="Test product")
        assert "EVIDENCE HIERARCHY" in result

    def test_system_prompt_no_tier_structure_when_disabled(self, claude_service):
        """System prompt omits EVIDENCE HIERARCHY when flag is off."""
        result = claude_service._build_system_prompt(product_context="Test product")
        assert "EVIDENCE HIERARCHY" not in result


# --- Research Validation ---


class TestResearchValidation:
    """Tests for validation checks."""

    def test_edp_sources_pass_empty(self, claude_service):
        assert ClaudeService._check_edp_sources("") is None

    def test_edp_sources_pass_no_urgency(self, claude_service):
        assert ClaudeService._check_edp_sources("No immediate urgency signals identified.") is None

    def test_edp_sources_pass_no_existential(self, claude_service):
        assert ClaudeService._check_edp_sources("No existential data points found.") is None

    def test_edp_sources_pass_well_structured(self, claude_service):
        edp = """- **Signal**: PostgreSQL on app.example.com with 3x growth
- **Sources**: Tech scan of app.example.com, Series B press release
- **Threshold**: Single DB + growth creates performance cliff
- **Consequence**: Degradation within 3-6 months"""
        assert ClaudeService._check_edp_sources(edp) is None

    def test_edp_sources_fail_no_markers(self, claude_service):
        """Substantial text with bullets but no Signal/Sources markers → fail."""
        edp = """- The company is growing rapidly and their infrastructure needs to scale significantly to handle increased traffic and user demand across all regions
- Their primary database architecture might not handle the projected load going forward based on current growth trajectory and capacity analysis
- They should consider upgrading their infrastructure to modern distributed systems before the next quarter deadline"""
        result = ClaudeService._check_edp_sources(edp)
        assert result is not None
        assert "format not followed" in result

    def test_edp_sources_fail_signal_without_sources(self, claude_service):
        """Signal markers present but missing Sources → fail."""
        edp = """**Signal**: PostgreSQL detected on app.example.com
**Threshold**: Single DB with growth pressure
**Consequence**: Performance degradation risk"""
        result = ClaudeService._check_edp_sources(edp)
        assert result is not None
        assert "missing Sources" in result

    def test_edp_sources_fail_empty_after_colon(self, claude_service):
        """Sources: present but nothing after the colon → fail."""
        edp = """**Signal**: PostgreSQL detected on app.example.com
**Sources**:
**Threshold**: Single DB with growth pressure
**Consequence**: Performance degradation risk"""
        result = ClaudeService._check_edp_sources(edp)
        assert result is not None
        assert "missing Sources" in result

    def test_concrete_pain_pass_with_source_ref(self, claude_service):
        sections = {
            "existential_data_points": "**Sources**: Detected on app.example.com",
            "business_problems": "General issues",
        }
        assert ClaudeService._check_concrete_pain(sections) is None

    def test_concrete_pain_pass_from_job_posting(self, claude_service):
        sections = {
            "existential_data_points": "",
            "hiring_signals": "From job posting: Senior DB Engineer open for 4 months",
        }
        assert ClaudeService._check_concrete_pain(sections) is None

    def test_concrete_pain_fail_no_refs(self, claude_service):
        sections = {
            "existential_data_points": "The company has growth challenges",
            "business_problems": "They need better tools",
            "hiring_signals": "Several roles are open",
            "confirmed_tech_stack": "React, Node.js",
        }
        result = ClaudeService._check_concrete_pain(sections)
        assert result is not None
        assert "No concrete source references" in result

    def test_concrete_pain_pass_empty_sections(self, claude_service):
        """Empty sections should pass (nothing to check)."""
        assert ClaudeService._check_concrete_pain({}) is None

    def test_score_calibration_pass_different_scores(self, claude_service):
        scores = {"pain": 75, "fit": 50, "timing": 30,
                  "pain_evidence": "evidence", "fit_evidence": "evidence", "timing_evidence": "evidence"}
        assert ClaudeService._check_score_calibration(scores) is None

    def test_score_calibration_fail_identical(self, claude_service):
        scores = {"pain": 60, "fit": 60, "timing": 60,
                  "pain_evidence": "evidence", "fit_evidence": "evidence", "timing_evidence": "evidence"}
        result = ClaudeService._check_score_calibration(scores)
        assert result is not None
        assert "identical" in result

    def test_score_calibration_fail_lazy_middle(self, claude_service):
        scores = {"pain": 62, "fit": 65, "timing": 63,
                  "pain_evidence": "evidence", "fit_evidence": "evidence", "timing_evidence": "evidence"}
        result = ClaudeService._check_score_calibration(scores)
        assert result is not None
        assert "lazy-middle" in result

    def test_score_calibration_pass_outside_lazy_band(self, claude_service):
        """Scores within 8 points but outside 55-75 → pass."""
        scores = {"pain": 82, "fit": 85, "timing": 80,
                  "pain_evidence": "evidence", "fit_evidence": "evidence", "timing_evidence": "evidence"}
        assert ClaudeService._check_score_calibration(scores) is None

    def test_score_calibration_fail_empty_evidence(self, claude_service):
        scores = {"pain": 75, "fit": 50, "timing": 30,
                  "pain_evidence": "", "fit_evidence": "evidence", "timing_evidence": "evidence"}
        result = ClaudeService._check_score_calibration(scores)
        assert result is not None
        assert "Empty evidence" in result

    def test_score_calibration_pass_no_signals_evidence(self, claude_service):
        """'No pain signals found' is valid non-empty evidence."""
        scores = {"pain": 20, "fit": 50, "timing": 30,
                  "pain_evidence": "No pain signals found", "fit_evidence": "ICP match", "timing_evidence": "Recent funding"}
        assert ClaudeService._check_score_calibration(scores) is None

    def test_score_calibration_skip_fewer_than_3(self, claude_service):
        """With fewer than 3 scores, spread check is skipped."""
        scores = {"pain": 60, "fit": 60}
        assert ClaudeService._check_score_calibration(scores) is None

    def test_generic_filler_pass_clean(self, claude_service):
        assert claude_service._check_generic_filler(
            "PostgreSQL detected on app.example.com with growth pressure",
            "Database scaling is a critical concern"
        ) is None

    def test_generic_filler_fail_companies_like_yours(self, claude_service):
        result = claude_service._check_generic_filler(
            "Companies like yours often struggle with scaling",
            "Database performance is critical"
        )
        assert result is not None
        assert "companies like yours" in result

    def test_generic_filler_fail_organizations_in_this_space(self, claude_service):
        result = claude_service._check_generic_filler(
            "No issues here",
            "Organizations in this space typically face these challenges"
        )
        assert result is not None
        assert "organizations in this space" in result

    def test_generic_filler_case_insensitive(self, claude_service):
        result = claude_service._check_generic_filler(
            "COMPANIES LIKE YOURS need better tools",
            ""
        )
        assert result is not None

    def test_validate_research_all_pass(self, claude_service):
        sections = {
            "existential_data_points": "**Signal**: DB scaling\n**Sources**: Detected on app.example.com",
            "business_problems": "From job posting: scaling issues",
            "hiring_signals": "Open for 4 months",
            "confirmed_tech_stack": "PostgreSQL",
        }
        scores = {"pain": 75, "fit": 50, "timing": 30,
                  "pain_evidence": "DB scaling", "fit_evidence": "ICP match", "timing_evidence": "Hiring"}
        result = claude_service._validate_research(sections, scores)
        assert result.is_valid
        assert len(result.failed_checks) == 0

    def test_validate_research_multiple_failures(self, claude_service):
        sections = {
            "existential_data_points": "Companies like yours often struggle with these problems and need solutions.",
            "business_problems": "Generic issues that many businesses face in the current market.",
            "hiring_signals": "Several roles exist",
            "confirmed_tech_stack": "Various technologies",
        }
        # EDP has no markers + generic filler + no concrete refs
        # And identical scores
        scores = {"pain": 60, "fit": 60, "timing": 60,
                  "pain_evidence": "Generic", "fit_evidence": "Generic", "timing_evidence": "Generic"}
        result = claude_service._validate_research(sections, scores)
        assert not result.is_valid
        assert len(result.failed_checks) >= 2


# --- Research Validation Repair ---


class TestResearchValidationRepair:
    """Tests for repair call shape and fail-open behavior."""

    @pytest.mark.asyncio
    async def test_repair_uses_4_message_shape(self):
        """Repair call sends exactly 4 messages: system, user, assistant, repair."""
        # Initial response that will fail validation (identical scores)
        initial_response = MagicMock()
        initial_response.choices = [MagicMock()]
        initial_response.choices[0].message.content = """## Company Overview
Test company

## Existential Data Points
Companies like yours struggle with scaling.

## Opportunity Score
SCORE_PAIN: 60
SCORE_PAIN_EVIDENCE: Generic pain
SCORE_FIT: 60
SCORE_FIT_EVIDENCE: Generic fit
SCORE_TIMING: 60
SCORE_TIMING_EVIDENCE: Generic timing
SCORE_COMPOSITE: 60
SCORE_SUMMARY: Medium opportunity
"""

        # Repaired response that passes
        repaired_response = MagicMock()
        repaired_response.choices = [MagicMock()]
        repaired_response.choices[0].message.content = """## Company Overview
Test company

## Existential Data Points
**Signal**: PostgreSQL detected on app.example.com
**Sources**: Tech scan, job posting analysis
**Threshold**: Single DB with growth pressure
**Consequence**: Performance risk within 6 months

## Stated Business Problems
From job posting: Database scaling challenges mentioned.

## Opportunity Score
SCORE_PAIN: 72
SCORE_PAIN_EVIDENCE: - DB scaling pressure from job postings
SCORE_FIT: 55
SCORE_FIT_EVIDENCE: - Moderate ICP alignment
SCORE_TIMING: 38
SCORE_TIMING_EVIDENCE: - Limited urgency signals
SCORE_COMPOSITE: 57
SCORE_SUMMARY: Moderate opportunity with clear pain but limited timing.
"""

        with patch("services.claude.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                openrouter_api_key="test-key",
                research_model="google/gemini-2.5-flash",
                research_tight_writing_enabled=False,
                research_tiered_prompt_enabled=False,
                research_validation_enabled=True,
            )
            with patch("services.claude.AsyncOpenAI") as mock_openai:
                mock_client = AsyncMock()
                mock_client.chat.completions.create = AsyncMock(
                    side_effect=[initial_response, repaired_response]
                )
                mock_openai.return_value = mock_client

                service = ClaudeService()
                scraped = ScrapedContent(homepage="Test")

                await service.generate_research_document(
                    company_url="https://example.com",
                    scraped=scraped,
                    product_context="Database software",
                )

                # Should have been called twice (initial + repair)
                assert mock_client.chat.completions.create.call_count == 2

                # Check the repair call has 4 messages
                repair_call = mock_client.chat.completions.create.call_args_list[1]
                repair_messages = repair_call[1]["messages"]
                assert len(repair_messages) == 4
                assert repair_messages[0]["role"] == "system"
                assert repair_messages[1]["role"] == "user"
                assert repair_messages[2]["role"] == "assistant"
                assert repair_messages[3]["role"] == "user"
                # Repair instructions should not duplicate the user_prompt
                assert "Research Data for" not in repair_messages[3]["content"]
                assert "Fix ONLY" in repair_messages[3]["content"]

    @pytest.mark.asyncio
    async def test_fail_open_keeps_original_on_repair_failure(self):
        """If repair also fails validation, original output is preserved."""
        bad_response = MagicMock()
        bad_response.choices = [MagicMock()]
        bad_response.choices[0].message.content = """## Company Overview
Test company

## Existential Data Points
Companies like yours struggle.

## Opportunity Score
SCORE_PAIN: 60
SCORE_PAIN_EVIDENCE: Generic
SCORE_FIT: 60
SCORE_FIT_EVIDENCE: Generic
SCORE_TIMING: 60
SCORE_TIMING_EVIDENCE: Generic
SCORE_COMPOSITE: 60
SCORE_SUMMARY: Medium
"""

        # Repair also returns bad output
        still_bad_response = MagicMock()
        still_bad_response.choices = [MagicMock()]
        still_bad_response.choices[0].message.content = bad_response.choices[0].message.content

        with patch("services.claude.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                openrouter_api_key="test-key",
                research_model="google/gemini-2.5-flash",
                research_tight_writing_enabled=False,
                research_tiered_prompt_enabled=False,
                research_validation_enabled=True,
            )
            with patch("services.claude.AsyncOpenAI") as mock_openai:
                mock_client = AsyncMock()
                mock_client.chat.completions.create = AsyncMock(
                    side_effect=[bad_response, still_bad_response]
                )
                mock_openai.return_value = mock_client

                service = ClaudeService()
                scraped = ScrapedContent(homepage="Test")

                result = await service.generate_research_document(
                    company_url="https://example.com",
                    scraped=scraped,
                    product_context="Database software",
                )

                # Should still return the original (fail-open)
                assert result.company_overview == "Test company"
                assert result.pain_score == 60
                assert mock_client.chat.completions.create.call_count == 2

    @pytest.mark.asyncio
    async def test_fail_open_on_api_error(self):
        """If repair API call throws, original output is preserved."""
        initial_response = MagicMock()
        initial_response.choices = [MagicMock()]
        initial_response.choices[0].message.content = """## Company Overview
Test company

## Opportunity Score
SCORE_PAIN: 60
SCORE_PAIN_EVIDENCE: Generic
SCORE_FIT: 60
SCORE_FIT_EVIDENCE: Generic
SCORE_TIMING: 60
SCORE_TIMING_EVIDENCE: Generic
SCORE_COMPOSITE: 60
SCORE_SUMMARY: Medium
"""

        with patch("services.claude.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                openrouter_api_key="test-key",
                research_model="google/gemini-2.5-flash",
                research_tight_writing_enabled=False,
                research_tiered_prompt_enabled=False,
                research_validation_enabled=True,
            )
            with patch("services.claude.AsyncOpenAI") as mock_openai:
                mock_client = AsyncMock()
                mock_client.chat.completions.create = AsyncMock(
                    side_effect=[initial_response, RuntimeError("API error")]
                )
                mock_openai.return_value = mock_client

                service = ClaudeService()
                scraped = ScrapedContent(homepage="Test")

                result = await service.generate_research_document(
                    company_url="https://example.com",
                    scraped=scraped,
                    product_context="Database software",
                )

                # Fail-open: original output preserved
                assert result.company_overview == "Test company"
                assert result.pain_score == 60

    @pytest.mark.asyncio
    async def test_no_validation_when_flag_off(self):
        """When validation flag is off, no repair call happens even with bad output."""
        bad_response = MagicMock()
        bad_response.choices = [MagicMock()]
        bad_response.choices[0].message.content = """## Company Overview
Test

## Opportunity Score
SCORE_PAIN: 60
SCORE_PAIN_EVIDENCE: Generic
SCORE_FIT: 60
SCORE_FIT_EVIDENCE: Generic
SCORE_TIMING: 60
SCORE_TIMING_EVIDENCE: Generic
SCORE_COMPOSITE: 60
SCORE_SUMMARY: Medium
"""

        with patch("services.claude.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                openrouter_api_key="test-key",
                research_model="google/gemini-2.5-flash",
                research_tight_writing_enabled=False,
                research_tiered_prompt_enabled=False,
                research_validation_enabled=False,
            )
            with patch("services.claude.AsyncOpenAI") as mock_openai:
                mock_client = AsyncMock()
                mock_client.chat.completions.create = AsyncMock(return_value=bad_response)
                mock_openai.return_value = mock_client

                service = ClaudeService()
                scraped = ScrapedContent(homepage="Test")

                await service.generate_research_document(
                    company_url="https://example.com",
                    scraped=scraped,
                    product_context="Database software",
                )

                # Only 1 call (no repair)
                assert mock_client.chat.completions.create.call_count == 1
