"""Tests for WritingService prompt assembly and email parsing."""

import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock, AsyncMock

from models import ResearchDocument
from services.writing import WritingService


@pytest.fixture
def writing_service():
    """WritingService with mocked API client."""
    with patch("services.writing.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(
            openrouter_api_key="test-key",
            writing_model="mistralai/mistral-medium-3.1",
            pea_selector_enabled=False,
        )
        with patch("services.writing.AsyncOpenAI"):
            service = WritingService()
    return service


@pytest.fixture
def sample_document():
    """Minimal research document for prompt tests."""
    return ResearchDocument(
        id=1,
        company_url="https://acme.com",
        company_name="Acme Corp",
        created_at=datetime.now(timezone.utc),
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


@pytest.fixture
def full_document():
    """Document with all optional fields populated."""
    return ResearchDocument(
        id=1,
        company_url="https://acme.com",
        company_name="Acme Corp",
        created_at=datetime.now(timezone.utc),
        company_overview="Acme Corp builds enterprise software.",
        projects_initiatives="Launching new AI product line",
        confirmed_tech_stack="React, Node.js, MongoDB",
        hiring_signals="Hiring 5 engineers",
        business_problems="Scaling database performance issues",
        existential_data_points="Series B funding running out in 6 months",
        product_fit="Good fit for their data needs.",
        talking_points="Focus on scalability and cost reduction",
        key_contacts="John Doe (CTO), Jane Smith (VP Engineering)",
        information_gaps="",
        full_markdown="",
        opportunity_score=75,
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
        # Tech stack intentionally excluded from outreach context
        assert "React, Node.js" not in report

    def test_omits_optional_sections_when_empty(self, writing_service, sample_document):
        report = writing_service._build_report(sample_document, "Product")
        assert "Business Problems" not in report
        assert "Technology Stack" not in report

    def test_includes_existential_data_points(self, writing_service, sample_document):
        """Test uncovered lines 35-37: existential_data_points section."""
        sample_document.existential_data_points = "Series B funding running out"
        report = writing_service._build_report(sample_document, "Product")
        assert "## Existential Data Points (Urgency Signals)" in report
        assert "Series B funding running out" in report

    def test_includes_projects_initiatives(self, writing_service, sample_document):
        """Test uncovered lines 40-42: projects_initiatives section."""
        sample_document.projects_initiatives = "Launching new AI product line"
        report = writing_service._build_report(sample_document, "Product")
        assert "## Current Projects & Initiatives" in report
        assert "Launching new AI product line" in report

    def test_includes_talking_points(self, writing_service, sample_document):
        """Test uncovered lines 55-57: talking_points section."""
        sample_document.talking_points = "Focus on scalability and cost reduction"
        report = writing_service._build_report(sample_document, "Product")
        assert "## Recommended Talking Points" in report
        assert "Focus on scalability and cost reduction" in report

    def test_includes_key_contacts(self, writing_service, sample_document):
        """Test uncovered lines 60-62: key_contacts section."""
        sample_document.key_contacts = "John Doe (CTO), Jane Smith (VP Engineering)"
        report = writing_service._build_report(sample_document, "Product")
        assert "## Key Contacts" in report
        assert "John Doe (CTO)" in report

    def test_includes_seller_company(self, writing_service, sample_document):
        """Test uncovered line 66: seller_company parameter."""
        report = writing_service._build_report(
            sample_document,
            "Our product",
            seller_company="MongoDB Inc"
        )
        assert "**Company:** MongoDB Inc" in report

    def test_includes_problems_solved(self, writing_service, sample_document):
        """Test uncovered lines 70-72: problems_solved parameter."""
        report = writing_service._build_report(
            sample_document,
            "Our product",
            problems_solved="Database scalability, Performance optimization"
        )
        assert "## Specific Problems We Solve" in report
        assert "Database scalability, Performance optimization" in report

    def test_includes_retrieved_materials(self, writing_service, sample_document):
        """Test uncovered lines 75-78: retrieved_materials parameter."""
        materials = "Case Study: Acme Corp reduced costs by 40%"
        report = writing_service._build_report(
            sample_document,
            "Our product",
            retrieved_materials=materials
        )
        assert "## Sales Materials (Case Studies, Battle Cards, Proof Points)" in report
        assert "Acme Corp reduced costs by 40%" in report

    def test_all_optional_fields_together(self, writing_service, full_document):
        """Test report with all optional fields populated."""
        report = writing_service._build_report(
            full_document,
            "MongoDB Atlas",
            retrieved_materials="Case studies here",
            seller_company="MongoDB Inc",
            problems_solved="Scalability, Performance"
        )
        assert "## Existential Data Points" in report
        assert "## Current Projects & Initiatives" in report
        assert "## Technology Stack" not in report  # intentionally excluded from outreach
        assert "## Recommended Talking Points" in report
        assert "## Key Contacts" in report
        assert "**Company:** MongoDB Inc" in report
        assert "## Specific Problems We Solve" in report
        assert "## Sales Materials" in report


# --- _build_prompt: Section A stripping ---


class TestSectionAStripping:
    def test_high_score_includes_section_a(self, writing_service):
        prompt = writing_service._build_system_prompt(opportunity_score=70)
        assert "**SECTION A: FULL-CONFIDENCE PVP EXAMPLES**" in prompt
        assert "**ADDITIONAL PVP EXAMPLES**" in prompt

    def test_low_score_excludes_section_a(self, writing_service):
        prompt = writing_service._build_system_prompt(opportunity_score=30)
        assert "**SECTION A: FULL-CONFIDENCE PVP EXAMPLES**" not in prompt
        assert "**ADDITIONAL PVP EXAMPLES**" not in prompt

    def test_low_score_keeps_section_b(self, writing_service):
        prompt = writing_service._build_system_prompt(opportunity_score=30)
        assert "**SECTION B: PARTIAL-SIGNAL PVP EXAMPLES**" in prompt

    def test_low_score_adds_partial_signal_header(self, writing_service):
        prompt = writing_service._build_system_prompt(opportunity_score=30)
        assert "**PARTIAL-SIGNAL PVP EXAMPLES**" in prompt
        assert "when data is incomplete" in prompt

    def test_no_score_includes_section_a(self, writing_service):
        prompt = writing_service._build_system_prompt(opportunity_score=None)
        assert "**SECTION A: FULL-CONFIDENCE PVP EXAMPLES**" in prompt

    def test_score_boundary_49_strips(self, writing_service):
        prompt = writing_service._build_system_prompt(opportunity_score=49)
        assert "**SECTION A: FULL-CONFIDENCE PVP EXAMPLES**" not in prompt

    def test_score_boundary_50_keeps(self, writing_service):
        prompt = writing_service._build_system_prompt(opportunity_score=50)
        assert "**SECTION A: FULL-CONFIDENCE PVP EXAMPLES**" in prompt


# --- _build_prompt: partial-signal directive ---


class TestPartialSignalDirective:
    def test_low_score_includes_directive(self, writing_service):
        prompt = writing_service._build_user_prompt("test report", opportunity_score=30)
        assert "PARTIAL-SIGNAL MODE" in prompt

    def test_high_score_excludes_directive(self, writing_service):
        prompt = writing_service._build_user_prompt("test report", opportunity_score=70)
        assert "PARTIAL-SIGNAL MODE" not in prompt

    def test_low_score_includes_banned_phrases(self, writing_service):
        prompt = writing_service._build_user_prompt("test report", opportunity_score=30)
        assert '"no obvious"' in prompt
        assert '"basic"' in prompt
        assert '"might work fine now"' in prompt

    def test_low_score_excludes_self_review_closing(self, writing_service):
        prompt = writing_service._build_user_prompt("test report", opportunity_score=30)
        assert "FINAL CHECK" not in prompt

    def test_high_score_excludes_self_review_closing(self, writing_service):
        prompt = writing_service._build_user_prompt("test report", opportunity_score=70)
        assert "FINAL CHECK" not in prompt


# --- _build_prompt: MSP product type ---


class TestMSPProductType:
    def test_msp_includes_msp_block(self, writing_service):
        """Test uncovered line 126: MSP product type includes msp_block."""
        prompt = writing_service._build_user_prompt("test report", product_type="msp")
        assert "**PROFESSIONAL SERVICES / CONSULTANCY FRAMING -- APPLY TO ALL EMAILS:**" in prompt
        assert "operational complexity" in prompt
        assert "professional services" in prompt

    def test_saas_excludes_msp_block(self, writing_service):
        """Test default product_type does not include msp_block."""
        prompt = writing_service._build_user_prompt("test report", product_type="saas")
        assert "**PROFESSIONAL SERVICES / CONSULTANCY FRAMING -- APPLY TO ALL EMAILS:**" not in prompt

    def test_msp_with_low_score(self, writing_service):
        """Test MSP block with low confidence score."""
        prompt = writing_service._build_user_prompt(
            "test report",
            opportunity_score=30,
            product_type="msp"
        )
        assert "**PROFESSIONAL SERVICES / CONSULTANCY FRAMING -- APPLY TO ALL EMAILS:**" in prompt
        assert "PARTIAL-SIGNAL MODE" in prompt


# --- _build_prompt: structure ---


class TestPromptStructure:
    def test_includes_word_limits(self, writing_service):
        prompt = writing_service._build_system_prompt(opportunity_score=None)
        assert "75 words max" in prompt
        assert "100 words max" in prompt
        assert "60 words max" in prompt

    def test_includes_report(self, writing_service):
        prompt = writing_service._build_user_prompt("my custom report", opportunity_score=None)
        assert "my custom report" in prompt

    def test_includes_writing_style(self, writing_service):
        prompt = writing_service._build_system_prompt(opportunity_score=None)
        assert "**WRITING STYLE**" in prompt

    def test_includes_output_format(self, writing_service):
        prompt = writing_service._build_system_prompt(opportunity_score=None)
        assert "Subject 1:" in prompt
        assert "Email 1:" in prompt


# --- _parse_emails ---


class TestParseEmails:
    def test_parses_three_emails_with_subject_options(self, writing_service):
        response = """
<email_series>
<subject1>Test subject</subject1>
<subject2>Alternative angle</subject2>
<subject3>Third hook</subject3>

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
        emails, subject_options = writing_service._parse_emails(response)
        assert len(emails) == 3
        assert emails[0]["subject"] == "Test subject"
        assert emails[0]["body"] == "First email body."
        assert emails[1]["email_number"] == 2
        assert emails[2]["body"] == "Third email body."
        assert subject_options == ["Test subject", "Alternative angle", "Third hook"]

    def test_shared_subject_across_emails(self, writing_service):
        response = """
<email_series>
<subject1>Shared subject line</subject1>
<subject2>Option two</subject2>
<subject3>Option three</subject3>
<email1>Body 1</email1>
<email2>Body 2</email2>
<email3>Body 3</email3>
</email_series>
"""
        emails, subject_options = writing_service._parse_emails(response)
        # All emails default to the first subject option
        assert all(e["subject"] == "Shared subject line" for e in emails)
        assert len(subject_options) == 3

    def test_legacy_single_subject_fallback(self, writing_service):
        response = """
<email_series>
<subject1>Legacy subject</subject1>
<email1>Body 1</email1>
<email2>Body 2</email2>
<email3>Body 3</email3>
</email_series>
"""
        emails, subject_options = writing_service._parse_emails(response)
        assert emails[0]["subject"] == "Legacy subject"
        assert subject_options == ["Legacy subject"]

    def test_fallback_subject_when_missing(self, writing_service):
        response = "<email1>Body</email1>"
        emails, subject_options = writing_service._parse_emails(response)
        assert emails[0]["subject"] == "Following up"
        assert subject_options == ["Following up"]

    def test_handles_partial_response(self, writing_service):
        response = """
<email_series>
<subject1>Test</subject1>
<email1>Only one email returned.</email1>
</email_series>
"""
        emails, subject_options = writing_service._parse_emails(response)
        assert len(emails) == 1


# --- generate_email_sequence ---


class TestGenerateEmailSequence:
    @pytest.mark.asyncio
    async def test_generate_sequence_basic(self, sample_document):
        """Test uncovered lines 1569-1587: generate_email_sequence method."""
        with patch("services.writing.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(openrouter_api_key="test-key", writing_model="mistralai/mistral-medium-3.1", pea_selector_enabled=False)

            mock_message = MagicMock()
            mock_message.choices = [MagicMock()]
            mock_message.choices[0].message.content = """
Subject 1: Following up on database scaling

Email 1:
Hi, noticed you're growing fast. Curious how you're handling data scale.

Email 2:
Following up on my previous note about scaling.

Email 3:
Last check-in - still interested in discussing database performance?
"""

            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_message)

            with patch("services.writing.AsyncOpenAI") as mock_openai:
                mock_openai.return_value = mock_client

                service = WritingService()
                emails, subject_options = await service.generate_email_sequence(
                    sample_document,
                    "MongoDB Atlas - scalable database platform"
                )

        assert len(emails) == 3
        assert emails[0]["subject"] == "Following up on database scaling"
        assert "growing fast" in emails[0]["body"]
        assert len(subject_options) >= 1

        # Verify the API call was made correctly
        mock_client.chat.completions.create.assert_called_once()
        call_args = mock_client.chat.completions.create.call_args
        assert call_args.kwargs["model"] == "mistralai/mistral-medium-3.1"
        assert call_args.kwargs["max_tokens"] == 2000
        assert len(call_args.kwargs["messages"]) == 2
        assert call_args.kwargs["messages"][0]["role"] == "system"
        assert call_args.kwargs["messages"][1]["role"] == "user"

    @pytest.mark.asyncio
    async def test_generate_sequence_with_all_parameters(self, full_document):
        """Test generate_email_sequence with all optional parameters."""
        with patch("services.writing.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(openrouter_api_key="test-key", writing_model="mistralai/mistral-medium-3.1", pea_selector_enabled=False)

            mock_message = MagicMock()
            mock_message.choices = [MagicMock()]
            mock_message.choices[0].message.content = """
<email_series>
<subject>Test</subject>
<email1>Body 1</email1>
<email2>Body 2</email2>
<email3>Body 3</email3>
</email_series>
"""

            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_message)

            with patch("services.writing.AsyncOpenAI") as mock_openai:
                mock_openai.return_value = mock_client

                service = WritingService()
                emails, subject_options = await service.generate_email_sequence(
                    full_document,
                    "MongoDB Atlas",
                    product_type="saas",
                    retrieved_materials="Case study: 40% cost reduction",
                    seller_company="MongoDB Inc",
                    problems_solved="Scalability, Performance"
                )

        assert len(emails) == 3

        # Verify the user prompt includes all the optional parameters
        call_args = mock_client.chat.completions.create.call_args
        user_prompt = call_args.kwargs["messages"][1]["content"]
        assert "MongoDB Inc" in user_prompt
        assert "Scalability, Performance" in user_prompt
        assert "Case study: 40% cost reduction" in user_prompt

    @pytest.mark.asyncio
    async def test_generate_sequence_msp_type(self, sample_document):
        """Test generate_email_sequence with MSP product type."""
        with patch("services.writing.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(openrouter_api_key="test-key", writing_model="mistralai/mistral-medium-3.1", pea_selector_enabled=False)

            mock_message = MagicMock()
            mock_message.choices = [MagicMock()]
            mock_message.choices[0].message.content = """
<email_series>
<subject>IT management overhead</subject>
<email1>Body 1</email1>
<email2>Body 2</email2>
<email3>Body 3</email3>
</email_series>
"""

            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_message)

            with patch("services.writing.AsyncOpenAI") as mock_openai:
                mock_openai.return_value = mock_client

                service = WritingService()
                emails, subject_options = await service.generate_email_sequence(
                    sample_document,
                    "Managed IT Services",
                    product_type="msp"
                )

        # Verify MSP framing was included in the user prompt
        call_args = mock_client.chat.completions.create.call_args
        user_prompt = call_args.kwargs["messages"][1]["content"]
        assert "**PROFESSIONAL SERVICES / CONSULTANCY FRAMING -- APPLY TO ALL EMAILS:**" in user_prompt


# --- format_emails_markdown ---


class TestFormatEmailsMarkdown:
    def test_format_single_email(self, writing_service):
        """Test uncovered lines 1591-1599: format_emails_markdown method."""
        emails = [
            {
                "email_number": 1,
                "subject": "Test subject",
                "body": "This is the email body."
            }
        ]

        markdown = writing_service.format_emails_markdown(emails)

        assert "# Email Sequence" in markdown
        assert "## Email 1" in markdown
        assert "**Subject:** Test subject" in markdown
        assert "This is the email body." in markdown

    def test_format_multiple_emails(self, writing_service):
        """Test formatting multiple emails."""
        emails = [
            {
                "email_number": 1,
                "subject": "Shared subject",
                "body": "First email body."
            },
            {
                "email_number": 2,
                "subject": "Shared subject",
                "body": "Second email body."
            },
            {
                "email_number": 3,
                "subject": "Shared subject",
                "body": "Third email body."
            }
        ]

        markdown = writing_service.format_emails_markdown(emails)

        assert markdown.count("## Email") == 3
        assert markdown.count("**Subject:**") == 3
        assert markdown.count("---") == 3
        assert "First email body." in markdown
        assert "Second email body." in markdown
        assert "Third email body." in markdown

    def test_format_preserves_email_order(self, writing_service):
        """Test that emails are formatted in correct order."""
        emails = [
            {"email_number": 1, "subject": "Test", "body": "Body 1"},
            {"email_number": 2, "subject": "Test", "body": "Body 2"},
            {"email_number": 3, "subject": "Test", "body": "Body 3"}
        ]

        markdown = writing_service.format_emails_markdown(emails)

        # Check order by finding positions
        pos1 = markdown.find("Body 1")
        pos2 = markdown.find("Body 2")
        pos3 = markdown.find("Body 3")

        assert pos1 < pos2 < pos3

    def test_format_empty_list(self, writing_service):
        """Test formatting empty email list."""
        emails = []
        markdown = writing_service.format_emails_markdown(emails)
        assert "# Email Sequence" in markdown


# --- persona_context ---


class TestPersonaContext:
    def test_persona_context_included_in_report(self, writing_service, sample_document):
        """persona_context adds Target Contact section to report."""
        report = writing_service._build_report(
            sample_document, "Product",
            persona_context="**Name:** Jane Smith\n**Title:** VP Engineering"
        )
        assert "## Target Contact" in report
        assert "Jane Smith" in report
        assert "VP Engineering" in report

    def test_persona_context_omitted_when_empty(self, writing_service, sample_document):
        """No Target Contact section when persona_context is empty."""
        report = writing_service._build_report(sample_document, "Product", persona_context="")
        assert "## Target Contact" not in report

    def test_persona_instructions_in_prompt(self, writing_service):
        """Persona instructions appear in user prompt when has_persona=True."""
        prompt = writing_service._build_user_prompt("test report", has_persona=True)
        assert "**PERSONA-TARGETED OUTREACH:**" in prompt
        assert "first name naturally in EVERY email" in prompt

    def test_no_persona_instructions_without_persona(self, writing_service):
        """No persona instructions when has_persona=False."""
        prompt = writing_service._build_user_prompt("test report", has_persona=False)
        assert "**PERSONA-TARGETED OUTREACH:**" not in prompt

    def test_recommended_contacts_in_report(self, writing_service, sample_document):
        """recommended_contacts field appears in report."""
        sample_document.recommended_contacts = "VP of Engineering - owns scaling problems"
        report = writing_service._build_report(sample_document, "Product")
        assert "## Recommended Contacts" in report
        assert "VP of Engineering" in report

    def test_recommended_contacts_omitted_when_empty(self, writing_service, sample_document):
        """No Recommended Contacts section when field is empty."""
        report = writing_service._build_report(sample_document, "Product")
        assert "## Recommended Contacts" not in report


# --- _validate_sequence ---


class TestValidateSequence:
    def test_valid_sequence(self, writing_service):
        emails = [
            {"email_number": 1, "subject": "test", "body": "Short body here."},
            {"email_number": 2, "subject": "test", "body": "Another short body here."},
            {"email_number": 3, "subject": "test", "body": "Final short body."},
        ]
        valid, msg = writing_service._validate_sequence(emails, ["subj1"])
        assert valid is True
        assert msg == ""

    def test_wrong_email_count(self, writing_service):
        emails = [
            {"email_number": 1, "subject": "test", "body": "Body."},
            {"email_number": 2, "subject": "test", "body": "Body."},
        ]
        valid, msg = writing_service._validate_sequence(emails, ["subj1"])
        assert valid is False
        assert "Expected 3 emails" in msg

    def test_wrong_email_numbers(self, writing_service):
        emails = [
            {"email_number": 1, "subject": "test", "body": "Body."},
            {"email_number": 2, "subject": "test", "body": "Body."},
            {"email_number": 4, "subject": "test", "body": "Body."},
        ]
        valid, msg = writing_service._validate_sequence(emails, ["subj1"])
        assert valid is False
        assert "Email numbers must be 1,2,3" in msg

    def test_empty_subject(self, writing_service):
        emails = [
            {"email_number": 1, "subject": "", "body": "Body."},
            {"email_number": 2, "subject": "test", "body": "Body."},
            {"email_number": 3, "subject": "test", "body": "Body."},
        ]
        valid, msg = writing_service._validate_sequence(emails, ["subj1"])
        assert valid is False
        assert "empty subject" in msg

    def test_empty_body(self, writing_service):
        emails = [
            {"email_number": 1, "subject": "test", "body": "  "},
            {"email_number": 2, "subject": "test", "body": "Body."},
            {"email_number": 3, "subject": "test", "body": "Body."},
        ]
        valid, msg = writing_service._validate_sequence(emails, ["subj1"])
        assert valid is False
        assert "empty body" in msg

    def test_over_word_limit_passes_validation(self, writing_service):
        """Word limits are NOT checked by _validate_sequence — handled by shorten pipeline."""
        long_body = " ".join(["word"] * 80)  # 80 words, limit for email 1 is 75
        emails = [
            {"email_number": 1, "subject": "test", "body": long_body},
            {"email_number": 2, "subject": "test", "body": "Short."},
            {"email_number": 3, "subject": "test", "body": "Short."},
        ]
        valid, msg = writing_service._validate_sequence(emails, ["subj1"])
        assert valid is True

    def test_no_subject_options(self, writing_service):
        emails = [
            {"email_number": 1, "subject": "test", "body": "Body."},
            {"email_number": 2, "subject": "test", "body": "Body."},
            {"email_number": 3, "subject": "test", "body": "Body."},
        ]
        valid, msg = writing_service._validate_sequence(emails, [])
        assert valid is False
        assert "No subject options" in msg


# --- _repair_sequence_output ---


class TestRepairSequence:
    @pytest.mark.asyncio
    async def test_repair_calls_model(self, writing_service):
        """Repair sends malformed content to the model for reformatting."""
        mock_message = MagicMock()
        mock_message.choices = [MagicMock()]
        mock_message.choices[0].message.content = (
            "Subject 1: fixed subject\n"
            "Subject 2: option two\n"
            "Subject 3: option three\n\n"
            "Email 1:\nFixed body one.\n\n"
            "Email 2:\nFixed body two.\n\n"
            "Email 3:\nFixed body three.\n"
        )
        writing_service.client = AsyncMock()
        writing_service.client.chat.completions.create = AsyncMock(return_value=mock_message)

        result = await writing_service._repair_sequence_output("broken output")

        assert "Subject 1: fixed subject" in result
        writing_service.client.chat.completions.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_repair_strips_emdashes(self, writing_service):
        """Repair pass removes em/en dashes from model output."""
        mock_message = MagicMock()
        mock_message.choices = [MagicMock()]
        mock_message.choices[0].message.content = "Subject 1: test \u2014 subject\n\nEmail 1:\nbody"
        writing_service.client = AsyncMock()
        writing_service.client.chat.completions.create = AsyncMock(return_value=mock_message)

        result = await writing_service._repair_sequence_output("broken")
        assert "\u2014" not in result
        assert " - " in result


# --- _over_limit_emails ---


class TestOverLimitEmails:
    def test_detects_over_limit(self, writing_service):
        emails = [
            {"email_number": 1, "body": " ".join(["word"] * 80)},  # limit 75
            {"email_number": 2, "body": " ".join(["word"] * 50)},  # limit 100
            {"email_number": 3, "body": " ".join(["word"] * 65)},  # limit 60
        ]
        over = writing_service._over_limit_emails(emails)
        assert len(over) == 2
        numbers = {o["email_number"] for o in over}
        assert numbers == {1, 3}

    def test_all_within_limit(self, writing_service):
        emails = [
            {"email_number": 1, "body": " ".join(["word"] * 70)},
            {"email_number": 2, "body": " ".join(["word"] * 90)},
            {"email_number": 3, "body": " ".join(["word"] * 55)},
        ]
        over = writing_service._over_limit_emails(emails)
        assert len(over) == 0


# --- PEA selector ---


class TestPEASelector:
    def test_high_score_uses_full_mode(self):
        from services.pea_selector import select_examples
        result = select_examples(opportunity_score=70)
        assert result["mode"] == "full"
        assert result["examples_count"] > 0

    def test_low_score_uses_partial_mode(self):
        from services.pea_selector import select_examples
        result = select_examples(opportunity_score=30)
        assert result["mode"] == "partial"
        assert result["examples_count"] > 0

    def test_msp_prioritizes_msp_example(self):
        from services.pea_selector import select_examples
        result = select_examples(opportunity_score=70, product_type="msp")
        assert result["mode"] == "full"
        # MSP example should be first
        assert any("MSP" in ex or "law firm" in ex.lower() for ex in result["examples"])

    def test_load_prompt_sections_default_path(self):
        from services.pea_selector import load_prompt_sections
        sections = load_prompt_sections(opportunity_score=70, use_selector=False)
        assert sections["rules_core"]
        assert sections["subject_rules"]
        assert sections["examples"]
        assert sections["mode"] == "full"
        assert "**ADDITIONAL PVP EXAMPLES**" in sections["examples"]

    def test_load_prompt_sections_partial_path(self):
        from services.pea_selector import load_prompt_sections
        sections = load_prompt_sections(opportunity_score=30, use_selector=False)
        assert sections["mode"] == "partial"
        assert "**PARTIAL-SIGNAL PVP EXAMPLES**" in sections["examples"]

    def test_load_prompt_sections_selector_path(self):
        from services.pea_selector import load_prompt_sections
        sections = load_prompt_sections(opportunity_score=70, use_selector=True)
        assert sections["mode"] == "full"
        assert sections["examples_count"] > 0

    def test_prompt_composition_includes_all_parts(self, writing_service):
        """_build_system_prompt composes rules + subject rules + examples."""
        prompt = writing_service._build_system_prompt(opportunity_score=70)
        assert "**WRITING STYLE**" in prompt
        assert "Subject 1:" in prompt
        assert "**SECTION A: FULL-CONFIDENCE PVP EXAMPLES**" in prompt


# --- generate_email_sequence validation flow ---


class TestGenerateValidationFlow:
    @pytest.mark.asyncio
    async def test_validation_failure_raises_error(self, sample_document):
        """When initial parse returns <3 emails and repair also fails, raises SequenceValidationError."""
        from services.writing import SequenceValidationError

        with patch("services.writing.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                openrouter_api_key="test-key",
                writing_model="mistralai/mistral-medium-3.1",
                pea_selector_enabled=False,
            )

            # Initial call returns 1 email (fails validation)
            mock_initial = MagicMock()
            mock_initial.choices = [MagicMock()]
            mock_initial.choices[0].message.content = "<email1>Only one email.</email1>"

            # Repair also returns 1 email
            mock_repair = MagicMock()
            mock_repair.choices = [MagicMock()]
            mock_repair.choices[0].message.content = "Email 1:\nStill only one."

            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(
                side_effect=[mock_initial, mock_repair]
            )

            with patch("services.writing.AsyncOpenAI") as mock_openai:
                mock_openai.return_value = mock_client
                service = WritingService()
                with pytest.raises(SequenceValidationError) as exc_info:
                    await service.generate_email_sequence(sample_document, "Product X")

                assert exc_info.value.code == "sequence_repair_failed"

    @pytest.mark.asyncio
    async def test_repair_success_continues(self, sample_document):
        """When initial output is malformed but repair succeeds, returns emails."""
        with patch("services.writing.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                openrouter_api_key="test-key",
                writing_model="mistralai/mistral-medium-3.1",
                pea_selector_enabled=False,
            )

            # Initial call returns malformed (1 email)
            mock_initial = MagicMock()
            mock_initial.choices = [MagicMock()]
            mock_initial.choices[0].message.content = "<email1>Only one.</email1>"

            # Repair returns valid 3-email output
            repaired = (
                "<email_series>\n"
                "<subject1>fixed subj</subject1>\n"
                "<email1>Body one.</email1>\n"
                "<email2>Body two.</email2>\n"
                "<email3>Body three.</email3>\n"
                "</email_series>"
            )
            mock_repair = MagicMock()
            mock_repair.choices = [MagicMock()]
            mock_repair.choices[0].message.content = repaired

            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(
                side_effect=[mock_initial, mock_repair]
            )

            with patch("services.writing.AsyncOpenAI") as mock_openai:
                mock_openai.return_value = mock_client
                service = WritingService()
                emails, subject_options = await service.generate_email_sequence(
                    sample_document, "Product X"
                )

                assert len(emails) == 3
                assert len(subject_options) >= 1
