"""Tests for WritingService prompt assembly and email parsing."""

import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock

from models import ResearchDocument
from services.writing import WritingService


@pytest.fixture
def writing_service():
    """WritingService with mocked API client."""
    with patch("services.writing.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(anthropic_api_key="test-key")
        with patch("services.writing.anthropic.Anthropic"):
            service = WritingService()
    return service


@pytest.fixture
def sample_document():
    """Minimal research document for prompt tests."""
    return ResearchDocument(
        id=1,
        company_url="https://acme.com",
        company_name="Acme Corp",
        created_at=datetime.now(),
        company_overview="Acme Corp builds enterprise software.",
        projects_initiatives="",
        confirmed_tech_stack="",
        hiring_signals="",
        business_problems="",
        product_fit="Good fit for their data needs.",
        talking_points="",
        information_gaps="",
        full_markdown="",
    )


# --- _build_report ---


class TestBuildReport:
    def test_includes_company_name(self, writing_service, sample_document):
        report = writing_service._build_report(sample_document, "Our product does X.")
        assert "Acme Corp" in report

    def test_includes_product_context(self, writing_service, sample_document):
        report = writing_service._build_report(sample_document, "MongoDB Atlas")
        assert "MongoDB Atlas" in report

    def test_includes_optional_sections_when_present(self, writing_service, sample_document):
        sample_document.business_problems = "Scaling issues."
        sample_document.confirmed_tech_stack = "React, Node.js"
        report = writing_service._build_report(sample_document, "Product")
        assert "Scaling issues." in report
        assert "React, Node.js" in report

    def test_omits_optional_sections_when_empty(self, writing_service, sample_document):
        report = writing_service._build_report(sample_document, "Product")
        assert "Business Problems" not in report
        assert "Technology Stack" not in report


# --- _build_prompt: Section A stripping ---


class TestSectionAStripping:
    def test_high_score_includes_section_a(self, writing_service):
        prompt = writing_service._build_prompt("test report", opportunity_score=70)
        assert "**SECTION A: FULL-CONFIDENCE PVP EXAMPLES**" in prompt
        assert "**ADDITIONAL PVP EXAMPLES**" in prompt

    def test_low_score_excludes_section_a(self, writing_service):
        prompt = writing_service._build_prompt("test report", opportunity_score=30)
        assert "**SECTION A: FULL-CONFIDENCE PVP EXAMPLES**" not in prompt
        assert "**ADDITIONAL PVP EXAMPLES**" not in prompt

    def test_low_score_keeps_section_b(self, writing_service):
        prompt = writing_service._build_prompt("test report", opportunity_score=30)
        assert "**SECTION B: PARTIAL-SIGNAL PVP EXAMPLES**" in prompt

    def test_low_score_adds_partial_signal_header(self, writing_service):
        prompt = writing_service._build_prompt("test report", opportunity_score=30)
        assert "**PARTIAL-SIGNAL PVP EXAMPLES**" in prompt
        assert "when data is incomplete" in prompt

    def test_no_score_includes_section_a(self, writing_service):
        prompt = writing_service._build_prompt("test report", opportunity_score=None)
        assert "**SECTION A: FULL-CONFIDENCE PVP EXAMPLES**" in prompt

    def test_score_boundary_49_strips(self, writing_service):
        prompt = writing_service._build_prompt("test report", opportunity_score=49)
        assert "**SECTION A: FULL-CONFIDENCE PVP EXAMPLES**" not in prompt

    def test_score_boundary_50_keeps(self, writing_service):
        prompt = writing_service._build_prompt("test report", opportunity_score=50)
        assert "**SECTION A: FULL-CONFIDENCE PVP EXAMPLES**" in prompt


# --- _build_prompt: partial-signal directive ---


class TestPartialSignalDirective:
    def test_low_score_includes_directive(self, writing_service):
        prompt = writing_service._build_prompt("test report", opportunity_score=30)
        assert "PARTIAL-SIGNAL MODE" in prompt

    def test_high_score_excludes_directive(self, writing_service):
        prompt = writing_service._build_prompt("test report", opportunity_score=70)
        assert "PARTIAL-SIGNAL MODE" not in prompt

    def test_low_score_includes_banned_phrases(self, writing_service):
        prompt = writing_service._build_prompt("test report", opportunity_score=30)
        assert '"no obvious"' in prompt
        assert '"basic"' in prompt
        assert '"might work fine now"' in prompt

    def test_low_score_includes_self_review_closing(self, writing_service):
        prompt = writing_service._build_prompt("test report", opportunity_score=30)
        assert "FINAL CHECK" in prompt

    def test_high_score_excludes_self_review_closing(self, writing_service):
        prompt = writing_service._build_prompt("test report", opportunity_score=70)
        assert "FINAL CHECK" not in prompt


# --- _build_prompt: structure ---


class TestPromptStructure:
    def test_includes_word_limits(self, writing_service):
        prompt = writing_service._build_prompt("test report", opportunity_score=None)
        assert "75 words max" in prompt
        assert "100 words max" in prompt
        assert "60 words max" in prompt

    def test_includes_report(self, writing_service):
        prompt = writing_service._build_prompt("my custom report", opportunity_score=None)
        assert "my custom report" in prompt

    def test_includes_writing_style(self, writing_service):
        prompt = writing_service._build_prompt("test report", opportunity_score=None)
        assert "**WRITING STYLE**" in prompt

    def test_includes_output_format(self, writing_service):
        prompt = writing_service._build_prompt("test report", opportunity_score=None)
        assert "<email_series>" in prompt
        assert "<email1>" in prompt


# --- _parse_emails ---


class TestParseEmails:
    def test_parses_three_emails(self, writing_service):
        response = """
<email_series>
<subject>Test subject</subject>

<email1>
First email body.
</email1>

<email2>
Second email body.
</email2>

<email3>
Third email body.
</email3>
</email_series>
"""
        emails = writing_service._parse_emails(response)
        assert len(emails) == 3
        assert emails[0]["subject"] == "Test subject"
        assert emails[0]["body"] == "First email body."
        assert emails[1]["email_number"] == 2
        assert emails[2]["body"] == "Third email body."

    def test_shared_subject_across_emails(self, writing_service):
        response = """
<email_series>
<subject>Shared subject line</subject>
<email1>Body 1</email1>
<email2>Body 2</email2>
<email3>Body 3</email3>
</email_series>
"""
        emails = writing_service._parse_emails(response)
        assert all(e["subject"] == "Shared subject line" for e in emails)

    def test_fallback_subject_when_missing(self, writing_service):
        response = "<email1>Body</email1>"
        emails = writing_service._parse_emails(response)
        assert emails[0]["subject"] == "Following up"

    def test_handles_partial_response(self, writing_service):
        response = """
<email_series>
<subject>Test</subject>
<email1>Only one email returned.</email1>
</email_series>
"""
        emails = writing_service._parse_emails(response)
        assert len(emails) == 1
