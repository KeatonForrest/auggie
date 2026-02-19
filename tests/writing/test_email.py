"""Tests for EmailStrategy: prompt assembly, parsing, validation, and integration."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from models import ResearchDocument
from services.writing import WritingService, SequenceValidationError
from services.writing.email import _validate_subject_line
from services.writing.types import GenerationContext


# --- _build_prompt: Section A stripping ---


class TestSectionAStripping:
    def test_high_score_includes_section_a(self, email_strategy):
        ctx = GenerationContext(document=None, product_context="", report="", opportunity_score=70)
        prompt = email_strategy.build_system_prompt(ctx)
        assert "**SECTION A: FULL-CONFIDENCE PVP EXAMPLES**" in prompt
        assert "**ADDITIONAL PVP EXAMPLES**" in prompt

    def test_low_score_excludes_section_a(self, email_strategy):
        ctx = GenerationContext(document=None, product_context="", report="", opportunity_score=30)
        prompt = email_strategy.build_system_prompt(ctx)
        assert "**SECTION A: FULL-CONFIDENCE PVP EXAMPLES**" not in prompt
        assert "**ADDITIONAL PVP EXAMPLES**" not in prompt

    def test_low_score_keeps_section_b(self, email_strategy):
        ctx = GenerationContext(document=None, product_context="", report="", opportunity_score=30)
        prompt = email_strategy.build_system_prompt(ctx)
        assert "**SECTION B: PARTIAL-SIGNAL PVP EXAMPLES**" in prompt

    def test_low_score_adds_partial_signal_header(self, email_strategy):
        ctx = GenerationContext(document=None, product_context="", report="", opportunity_score=30)
        prompt = email_strategy.build_system_prompt(ctx)
        assert "**PARTIAL-SIGNAL PVP EXAMPLES**" in prompt
        assert "when data is incomplete" in prompt

    def test_no_score_includes_section_a(self, email_strategy):
        ctx = GenerationContext(document=None, product_context="", report="", opportunity_score=None)
        prompt = email_strategy.build_system_prompt(ctx)
        assert "**SECTION A: FULL-CONFIDENCE PVP EXAMPLES**" in prompt

    def test_score_boundary_49_strips(self, email_strategy):
        ctx = GenerationContext(document=None, product_context="", report="", opportunity_score=49)
        prompt = email_strategy.build_system_prompt(ctx)
        assert "**SECTION A: FULL-CONFIDENCE PVP EXAMPLES**" not in prompt

    def test_score_boundary_50_keeps(self, email_strategy):
        ctx = GenerationContext(document=None, product_context="", report="", opportunity_score=50)
        prompt = email_strategy.build_system_prompt(ctx)
        assert "**SECTION A: FULL-CONFIDENCE PVP EXAMPLES**" in prompt


# --- _build_prompt: partial-signal directive ---


class TestPartialSignalDirective:
    def test_low_score_includes_directive(self, email_strategy):
        ctx = GenerationContext(document=None, product_context="", report="test report", opportunity_score=30)
        prompt = email_strategy.build_user_prompt(ctx)
        assert "PARTIAL-SIGNAL MODE" in prompt

    def test_high_score_excludes_directive(self, email_strategy):
        ctx = GenerationContext(document=None, product_context="", report="test report", opportunity_score=70)
        prompt = email_strategy.build_user_prompt(ctx)
        assert "PARTIAL-SIGNAL MODE" not in prompt

    def test_low_score_includes_banned_phrases(self, email_strategy):
        ctx = GenerationContext(document=None, product_context="", report="test report", opportunity_score=30)
        prompt = email_strategy.build_user_prompt(ctx)
        assert '"no obvious"' in prompt
        assert '"basic"' in prompt
        assert '"might work fine now"' in prompt

    def test_low_score_excludes_self_review_closing(self, email_strategy):
        ctx = GenerationContext(document=None, product_context="", report="test report", opportunity_score=30)
        prompt = email_strategy.build_user_prompt(ctx)
        assert "FINAL CHECK" not in prompt

    def test_high_score_excludes_self_review_closing(self, email_strategy):
        ctx = GenerationContext(document=None, product_context="", report="test report", opportunity_score=70)
        prompt = email_strategy.build_user_prompt(ctx)
        assert "FINAL CHECK" not in prompt


# --- _build_prompt: MSP product type ---


class TestMSPProductType:
    def test_msp_includes_msp_block(self, email_strategy):
        ctx = GenerationContext(document=None, product_context="", report="test report", product_type="msp")
        prompt = email_strategy.build_user_prompt(ctx)
        assert "**PROFESSIONAL SERVICES / CONSULTANCY FRAMING -- APPLY TO ALL EMAILS:**" in prompt
        assert "operational complexity" in prompt
        assert "professional services" in prompt

    def test_saas_excludes_msp_block(self, email_strategy):
        ctx = GenerationContext(document=None, product_context="", report="test report", product_type="saas")
        prompt = email_strategy.build_user_prompt(ctx)
        assert "**PROFESSIONAL SERVICES / CONSULTANCY FRAMING -- APPLY TO ALL EMAILS:**" not in prompt

    def test_msp_with_low_score(self, email_strategy):
        ctx = GenerationContext(document=None, product_context="", report="test report", product_type="msp", opportunity_score=30)
        prompt = email_strategy.build_user_prompt(ctx)
        assert "**PROFESSIONAL SERVICES / CONSULTANCY FRAMING -- APPLY TO ALL EMAILS:**" in prompt
        assert "PARTIAL-SIGNAL MODE" in prompt


# --- _build_prompt: structure ---


class TestPromptStructure:
    def test_includes_word_limits(self, email_strategy):
        ctx = GenerationContext(document=None, product_context="", report="", opportunity_score=None)
        prompt = email_strategy.build_system_prompt(ctx)
        assert "75 words max" in prompt
        assert "100 words max" in prompt
        assert "60 words max" in prompt

    def test_includes_report(self, email_strategy):
        ctx = GenerationContext(document=None, product_context="", report="my custom report", opportunity_score=None)
        prompt = email_strategy.build_user_prompt(ctx)
        assert "my custom report" in prompt

    def test_includes_writing_style(self, email_strategy):
        ctx = GenerationContext(document=None, product_context="", report="", opportunity_score=None)
        prompt = email_strategy.build_system_prompt(ctx)
        assert "**WRITING STYLE**" in prompt

    def test_includes_output_format(self, email_strategy):
        ctx = GenerationContext(document=None, product_context="", report="", opportunity_score=None)
        prompt = email_strategy.build_system_prompt(ctx)
        assert "Subject 1:" in prompt
        assert "Email 1:" in prompt

    def test_persona_instructions_in_prompt(self, email_strategy):
        ctx = GenerationContext(document=None, product_context="", report="test report", has_persona=True)
        prompt = email_strategy.build_user_prompt(ctx)
        assert "**PERSONA-TARGETED OUTREACH:**" in prompt
        assert "first name naturally in EVERY email" in prompt

    def test_no_persona_instructions_without_persona(self, email_strategy):
        ctx = GenerationContext(document=None, product_context="", report="test report", has_persona=False)
        prompt = email_strategy.build_user_prompt(ctx)
        assert "**PERSONA-TARGETED OUTREACH:**" not in prompt


# --- parse_output ---


class TestParseEmails:
    def test_parses_three_emails_with_subject_options(self, email_strategy):
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
        ctx = GenerationContext(document=None, product_context="", report="")
        emails, subject_options = email_strategy.parse_output(response, ctx)
        assert len(emails) == 3
        assert emails[0]["subject"] == "Test subject"
        assert emails[0]["body"] == "First email body."
        assert emails[1]["email_number"] == 2
        assert emails[2]["body"] == "Third email body."
        assert subject_options == ["Test subject", "Alternative angle", "Third hook"]

    def test_shared_subject_across_emails(self, email_strategy):
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
        ctx = GenerationContext(document=None, product_context="", report="")
        emails, subject_options = email_strategy.parse_output(response, ctx)
        assert all(e["subject"] == "Shared subject line" for e in emails)
        assert len(subject_options) == 3

    def test_legacy_single_subject_fallback(self, email_strategy):
        response = """
<email_series>
<subject1>Legacy subject</subject1>
<email1>Body 1</email1>
<email2>Body 2</email2>
<email3>Body 3</email3>
</email_series>
"""
        ctx = GenerationContext(document=None, product_context="", report="")
        emails, subject_options = email_strategy.parse_output(response, ctx)
        assert emails[0]["subject"] == "Legacy subject"
        assert subject_options == ["Legacy subject"]

    def test_fallback_subject_when_missing(self, email_strategy):
        ctx = GenerationContext(document=None, product_context="", report="")
        emails, subject_options = email_strategy.parse_output("<email1>Body</email1>", ctx)
        assert emails[0]["subject"] == "Following up"
        assert subject_options == ["Following up"]

    def test_handles_partial_response(self, email_strategy):
        response = """
<email_series>
<subject1>Test</subject1>
<email1>Only one email returned.</email1>
</email_series>
"""
        ctx = GenerationContext(document=None, product_context="", report="")
        emails, subject_options = email_strategy.parse_output(response, ctx)
        assert len(emails) == 1


# --- generate_email_sequence ---


class TestGenerateEmailSequence:
    @pytest.mark.asyncio
    async def test_generate_sequence_basic(self, sample_document):
        with patch("services.writing.service.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                openrouter_api_key="test-key",
                writing_model="mistralai/mistral-medium-3.1",
                writing_model_email="",
                pea_selector_enabled=False,
            )

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
            mock_message.usage = None

            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_message)

            with patch("services.writing.service.AsyncOpenAI") as mock_openai:
                mock_openai.return_value = mock_client

                service = WritingService()
                emails, subject_options = await service.generate_email_sequence(
                    sample_document,
                    "MongoDB Atlas - scalable database platform"
                )

        assert len(emails) == 3
        assert emails[0]["subject"] == "following up on database scaling"
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
        with patch("services.writing.service.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                openrouter_api_key="test-key",
                writing_model="mistralai/mistral-medium-3.1",
                writing_model_email="",
                pea_selector_enabled=False,
            )

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
            mock_message.usage = None

            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_message)

            with patch("services.writing.service.AsyncOpenAI") as mock_openai:
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

        call_args = mock_client.chat.completions.create.call_args
        user_prompt = call_args.kwargs["messages"][1]["content"]
        assert "MongoDB Inc" in user_prompt
        assert "Scalability, Performance" in user_prompt
        assert "Case study: 40% cost reduction" in user_prompt

    @pytest.mark.asyncio
    async def test_generate_sequence_msp_type(self, sample_document):
        with patch("services.writing.service.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                openrouter_api_key="test-key",
                writing_model="mistralai/mistral-medium-3.1",
                writing_model_email="",
                pea_selector_enabled=False,
            )

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
            mock_message.usage = None

            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_message)

            with patch("services.writing.service.AsyncOpenAI") as mock_openai:
                mock_openai.return_value = mock_client

                service = WritingService()
                emails, subject_options = await service.generate_email_sequence(
                    sample_document,
                    "Managed IT Services",
                    product_type="msp"
                )

        call_args = mock_client.chat.completions.create.call_args
        user_prompt = call_args.kwargs["messages"][1]["content"]
        assert "**PROFESSIONAL SERVICES / CONSULTANCY FRAMING -- APPLY TO ALL EMAILS:**" in user_prompt


# --- validate_sequence ---


class TestValidateSequence:
    def test_valid_sequence(self, email_strategy):
        emails = [
            {"email_number": 1, "subject": "test", "body": "Short body here."},
            {"email_number": 2, "subject": "test", "body": "Another short body here."},
            {"email_number": 3, "subject": "test", "body": "Final short body."},
        ]
        result = email_strategy.validate((emails, ["subj1"]), GenerationContext(document=None, product_context="", report=""))
        assert result.is_valid is True
        assert result.error_reason == ""

    def test_wrong_email_count(self, email_strategy):
        emails = [
            {"email_number": 1, "subject": "test", "body": "Body."},
            {"email_number": 2, "subject": "test", "body": "Body."},
        ]
        result = email_strategy.validate((emails, ["subj1"]), GenerationContext(document=None, product_context="", report=""))
        assert result.is_valid is False
        assert "Expected 3 emails" in result.error_reason

    def test_wrong_email_numbers(self, email_strategy):
        emails = [
            {"email_number": 1, "subject": "test", "body": "Body."},
            {"email_number": 2, "subject": "test", "body": "Body."},
            {"email_number": 4, "subject": "test", "body": "Body."},
        ]
        result = email_strategy.validate((emails, ["subj1"]), GenerationContext(document=None, product_context="", report=""))
        assert result.is_valid is False
        assert "Email numbers must be 1,2,3" in result.error_reason

    def test_empty_subject(self, email_strategy):
        emails = [
            {"email_number": 1, "subject": "", "body": "Body."},
            {"email_number": 2, "subject": "test", "body": "Body."},
            {"email_number": 3, "subject": "test", "body": "Body."},
        ]
        result = email_strategy.validate((emails, ["subj1"]), GenerationContext(document=None, product_context="", report=""))
        assert result.is_valid is False
        assert "empty subject" in result.error_reason

    def test_empty_body(self, email_strategy):
        emails = [
            {"email_number": 1, "subject": "test", "body": "  "},
            {"email_number": 2, "subject": "test", "body": "Body."},
            {"email_number": 3, "subject": "test", "body": "Body."},
        ]
        result = email_strategy.validate((emails, ["subj1"]), GenerationContext(document=None, product_context="", report=""))
        assert result.is_valid is False
        assert "empty body" in result.error_reason

    def test_over_word_limit_passes_validation(self, email_strategy):
        long_body = " ".join(["word"] * 80)
        emails = [
            {"email_number": 1, "subject": "test", "body": long_body},
            {"email_number": 2, "subject": "test", "body": "Short."},
            {"email_number": 3, "subject": "test", "body": "Short."},
        ]
        result = email_strategy.validate((emails, ["subj1"]), GenerationContext(document=None, product_context="", report=""))
        assert result.is_valid is True

    def test_no_subject_options(self, email_strategy):
        emails = [
            {"email_number": 1, "subject": "test", "body": "Body."},
            {"email_number": 2, "subject": "test", "body": "Body."},
            {"email_number": 3, "subject": "test", "body": "Body."},
        ]
        result = email_strategy.validate((emails, []), GenerationContext(document=None, product_context="", report=""))
        assert result.is_valid is False
        assert "No subject options" in result.error_reason


# --- repair_sequence_output ---


class TestRepairSequence:
    @pytest.mark.asyncio
    async def test_repair_calls_model(self, writing_service):
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
        mock_message.usage = None
        writing_service.client = AsyncMock()
        writing_service.client.chat.completions.create = AsyncMock(return_value=mock_message)

        # Test that the repair prompt is generated correctly
        repair_text = writing_service._email.repair_prompt("broken output", GenerationContext(document=None, product_context="", report=""), "")
        assert "MALFORMED OUTPUT" in repair_text
        assert "broken output" in repair_text


# --- over_limit_emails ---


class TestOverLimitEmails:
    def test_detects_over_limit(self, email_strategy):
        emails = [
            {"email_number": 1, "body": " ".join(["word"] * 80)},
            {"email_number": 2, "body": " ".join(["word"] * 50)},
            {"email_number": 3, "body": " ".join(["word"] * 65)},
        ]
        over = email_strategy.over_limit_emails(emails)
        assert len(over) == 2
        numbers = {o["email_number"] for o in over}
        assert numbers == {1, 3}

    def test_all_within_limit(self, email_strategy):
        emails = [
            {"email_number": 1, "body": " ".join(["word"] * 70)},
            {"email_number": 2, "body": " ".join(["word"] * 90)},
            {"email_number": 3, "body": " ".join(["word"] * 55)},
        ]
        over = email_strategy.over_limit_emails(emails)
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

    def test_prompt_composition_includes_all_parts(self, email_strategy):
        ctx = GenerationContext(document=None, product_context="", report="", opportunity_score=70)
        prompt = email_strategy.build_system_prompt(ctx)
        assert "**WRITING STYLE**" in prompt
        assert "Subject 1:" in prompt
        assert "**SECTION A: FULL-CONFIDENCE PVP EXAMPLES**" in prompt


# --- generate_email_sequence validation flow ---


class TestGenerateValidationFlow:
    @pytest.mark.asyncio
    async def test_validation_failure_raises_error(self, sample_document):
        with patch("services.writing.service.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                openrouter_api_key="test-key",
                writing_model="mistralai/mistral-medium-3.1",
                writing_model_email="",
                pea_selector_enabled=False,
            )

            mock_initial = MagicMock()
            mock_initial.choices = [MagicMock()]
            mock_initial.choices[0].message.content = "<email1>Only one email.</email1>"
            mock_initial.usage = None

            mock_repair = MagicMock()
            mock_repair.choices = [MagicMock()]
            mock_repair.choices[0].message.content = "Email 1:\nStill only one."
            mock_repair.usage = None

            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(
                side_effect=[mock_initial, mock_repair]
            )

            with patch("services.writing.service.AsyncOpenAI") as mock_openai:
                mock_openai.return_value = mock_client
                service = WritingService()
                with pytest.raises(SequenceValidationError) as exc_info:
                    await service.generate_email_sequence(sample_document, "Product X")

                assert exc_info.value.code == "sequence_repair_failed"

    @pytest.mark.asyncio
    async def test_repair_success_continues(self, sample_document):
        with patch("services.writing.service.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                openrouter_api_key="test-key",
                writing_model="mistralai/mistral-medium-3.1",
                writing_model_email="",
                pea_selector_enabled=False,
            )

            mock_initial = MagicMock()
            mock_initial.choices = [MagicMock()]
            mock_initial.choices[0].message.content = "<email1>Only one.</email1>"
            mock_initial.usage = None

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
            mock_repair.usage = None

            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(
                side_effect=[mock_initial, mock_repair]
            )

            with patch("services.writing.service.AsyncOpenAI") as mock_openai:
                mock_openai.return_value = mock_client
                service = WritingService()
                emails, subject_options = await service.generate_email_sequence(
                    sample_document, "Product X"
                )

                assert len(emails) == 3
                assert len(subject_options) >= 1


# --- Relevance prompt contract ---


class TestRelevancePromptContract:
    def test_gate_on_with_category_adds_directive(self, email_strategy):
        ctx = GenerationContext(document=None, product_context="", report="test report", product_category="database")
        prompt = email_strategy.build_user_prompt(ctx)
        assert "PRODUCT-RELEVANCE CONSTRAINT (DATABASE SELLER)" in prompt

    def test_empty_category_no_directive(self, email_strategy):
        ctx = GenerationContext(document=None, product_context="", report="test report", product_category="")
        prompt = email_strategy.build_user_prompt(ctx)
        assert "PRODUCT-RELEVANCE CONSTRAINT" not in prompt

    def test_category_specific_constraint_text(self, email_strategy):
        ctx = GenerationContext(document=None, product_context="", report="test report", product_category="database")
        prompt = email_strategy.build_user_prompt(ctx)
        assert "CDN, frontend" in prompt
        assert "database bottleneck" in prompt

    def test_fintech_constraint_injected(self, email_strategy):
        ctx = GenerationContext(document=None, product_context="", report="test report", product_category="fintech")
        prompt = email_strategy.build_user_prompt(ctx)
        assert "PRODUCT-RELEVANCE CONSTRAINT (FINTECH SELLER)" in prompt
        assert "payment flow" in prompt

    def test_healthtech_constraint_injected(self, email_strategy):
        ctx = GenerationContext(document=None, product_context="", report="test report", product_category="healthtech")
        prompt = email_strategy.build_user_prompt(ctx)
        assert "PRODUCT-RELEVANCE CONSTRAINT (HEALTHTECH SELLER)" in prompt
        assert "patient data" in prompt

    def test_martech_constraint_injected(self, email_strategy):
        ctx = GenerationContext(document=None, product_context="", report="test report", product_category="martech")
        prompt = email_strategy.build_user_prompt(ctx)
        assert "PRODUCT-RELEVANCE CONSTRAINT (MARTECH SELLER)" in prompt
        assert "customer data" in prompt

    def test_devtools_constraint_injected(self, email_strategy):
        ctx = GenerationContext(document=None, product_context="", report="test report", product_category="devtools")
        prompt = email_strategy.build_user_prompt(ctx)
        assert "PRODUCT-RELEVANCE CONSTRAINT (DEVTOOLS SELLER)" in prompt
        assert "developer experience" in prompt


class TestRelevanceGateIntegration:
    @pytest.mark.asyncio
    async def test_full_generate_with_gate_filters_and_adds_directive(self, sample_document):
        sample_document.talking_points = (
            "- React frontend rewrite underway\n"
            "- Database query latency is spiking under load"
        )

        with patch("services.writing.service.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                openrouter_api_key="test-key",
                writing_model="mistralai/mistral-medium-3.1",
                writing_model_email="",
                pea_selector_enabled=False,
                writing_relevance_gate_enabled=True,
            )

            mock_message = MagicMock()
            mock_message.choices = [MagicMock()]
            mock_message.choices[0].message.content = (
                "Subject 1: query latency\n\n"
                "Email 1:\nYour database queries are slowing down.\n\n"
                "Email 2:\nA similar company fixed this in weeks.\n\n"
                "Email 3:\nHappy to run a quick analysis."
            )
            mock_message.usage = None

            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_message)

            with patch("services.writing.service.AsyncOpenAI") as mock_openai:
                mock_openai.return_value = mock_client
                service = WritingService()
                emails, _ = await service.generate_email_sequence(
                    sample_document,
                    "MongoDB Atlas - scalable database platform",
                )

        assert len(emails) == 3

        call_args = mock_client.chat.completions.create.call_args
        user_prompt = call_args.kwargs["messages"][1]["content"]

        assert "React frontend rewrite" not in user_prompt
        assert "Database query latency" in user_prompt
        assert "PRODUCT-RELEVANCE CONSTRAINT (DATABASE SELLER)" in user_prompt


# --- Subject-line validation ---


class TestSubjectLineValidation:
    def test_lowercase_auto_fix(self):
        cleaned, issues = _validate_subject_line("Database Scaling")
        assert cleaned == "database scaling"
        assert issues == []

    def test_punctuation_strip_exclamation(self):
        cleaned, issues = _validate_subject_line("great deal!")
        assert cleaned == "great deal"
        assert issues == []

    def test_punctuation_strip_question(self):
        cleaned, issues = _validate_subject_line("pipeline issues?")
        assert cleaned == "pipeline issues"
        assert issues == []

    def test_ai_flagged(self):
        cleaned, issues = _validate_subject_line("ai scaling")
        assert any('"ai"' in i for i in issues)

    def test_digits_flagged(self):
        cleaned, issues = _validate_subject_line("q4 pipeline 2025")
        assert any("digits" in i for i in issues)

    def test_length_flagged(self):
        cleaned, issues = _validate_subject_line("this is a very long subject line indeed")
        assert any("too long" in i for i in issues)

    def test_clean_pass(self):
        cleaned, issues = _validate_subject_line("warehouse automation")
        assert cleaned == "warehouse automation"
        assert issues == []

    def test_fix_subject_lines_applies_to_emails(self, email_strategy):
        emails = [
            {"email_number": 1, "subject": "OLD Subject!", "body": "Body."},
            {"email_number": 2, "subject": "OLD Subject!", "body": "Body."},
            {"email_number": 3, "subject": "OLD Subject!", "body": "Body."},
        ]
        subject_options = ["OLD Subject!", "Option Two?", "Third!"]
        emails, opts, issues = email_strategy.fix_subject_lines(emails, subject_options)
        assert opts == ["old subject", "option two", "third"]
        assert all(e["subject"] == "old subject" for e in emails)
        assert issues == []

    def test_rewrite_subject_prompt_format(self, email_strategy):
        ctx = GenerationContext(document=None, product_context="", report="")
        prompt = email_strategy.rewrite_subject_prompt(
            ["ai growth", "pipeline 42", "very long subject line of many words"],
            ['contains standalone "ai"', "contains digits", "too long (7 words, max 6)"],
            ctx,
        )
        assert "Subject 1:" in prompt
        assert "ai growth" in prompt
        assert "MAX 4 words" in prompt
