"""Tests for LinkedIn connection request strategy."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from services.writing import WritingService, SequenceValidationError
from services.writing.types import GenerationContext, LINKEDIN_WORD_LIMITS


# --- LinkedIn system prompt (CR) ---


class TestLinkedInSystemPrompt:
    def test_cr_word_limit(self, linkedin_cr_strategy):
        ctx = GenerationContext(document=None, product_context="", report="", mode="connection_request")
        prompt = linkedin_cr_strategy.build_system_prompt(ctx)
        assert "25-45 words" in prompt
        assert "300" in prompt
        assert "Context" in prompt
        assert "No bridge sentence" in prompt

    def test_no_email_rules(self, linkedin_cr_strategy):
        ctx = GenerationContext(document=None, product_context="", report="", mode="connection_request")
        prompt = linkedin_cr_strategy.build_system_prompt(ctx)
        assert "PEA FRAMEWORK" not in prompt
        assert "Subject 1:" not in prompt
        assert "Email 1:" not in prompt

    def test_relevance_guardrail(self, linkedin_cr_strategy):
        ctx = GenerationContext(document=None, product_context="", report="", mode="connection_request")
        prompt = linkedin_cr_strategy.build_system_prompt(ctx)
        assert "RELEVANCE GUARDRAIL" in prompt
        assert "Only reference pains" in prompt


# --- LinkedIn quality gate (CR) ---


class TestLinkedInQualityGate:
    def test_over_300_chars_cr(self, linkedin_cr_strategy):
        long_words = " ".join(["longwordherex"] * 22)
        msg = f"Acme Corp {long_words} scaling?"
        assert len(msg.split()) < 45, f"Got {len(msg.split())} words"
        assert len(msg) > 300, f"Got {len(msg)} chars"
        ctx = GenerationContext(document=None, product_context="", report="", company_name="Acme Corp")
        result = linkedin_cr_strategy.validate(msg, ctx)
        assert result.is_valid is False
        assert "300 character limit" in result.error_reason

    def test_valid_cr_passes(self, linkedin_cr_strategy):
        msg = "Acme Corp's data growth and engineering expansion caught my eye. The companies at your stage usually hit a scaling inflection point. Curious how you're handling that?"
        ctx = GenerationContext(document=None, product_context="", report="", company_name="Acme Corp")
        result = linkedin_cr_strategy.validate(msg, ctx)
        assert result.is_valid is True

    def test_over_55_words_cr(self, linkedin_cr_strategy):
        words = ["word"] * 60
        words[5] = "Acme"
        words[6] = "Corp"
        msg = " ".join(words) + "?"
        ctx = GenerationContext(document=None, product_context="", report="", company_name="Acme Corp")
        result = linkedin_cr_strategy.validate(msg, ctx)
        assert result.is_valid is False
        assert "60 words" in result.error_reason


# --- LinkedIn message generation (CR) ---


class TestLinkedInMessageGeneration:
    @pytest.mark.asyncio
    async def test_happy_cr(self, sample_document):
        with patch("services.writing.service.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                openrouter_api_key="test-key",
                writing_model="mistralai/mistral-medium-3.1",
                writing_model_linkedin_connection="",
                pea_selector_enabled=False,
                writing_relevance_gate_enabled=False,
            )

            mock_message = MagicMock()
            mock_message.choices = [MagicMock()]
            mock_message.choices[0].message.content = (
                "Message:\n"
                "Acme Corp's data growth and engineering expansion caught my eye. "
                "The companies at your stage usually hit a scaling inflection point. "
                "Curious how you're handling that?"
            )
            mock_message.usage = None

            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_message)

            with patch("services.writing.service.AsyncOpenAI") as mock_openai:
                mock_openai.return_value = mock_client
                service = WritingService()
                result = await service.generate_linkedin_message(
                    document=sample_document,
                    product_context="MongoDB Atlas database",
                    linkedin_context={"content_type": "none", "low_confidence": True},
                    mode="connection_request",
                    problems_solved="database scalability",
                )

        assert result["mode"] == "connection_request"
        assert result["word_count"] <= 45
        assert result["char_count"] <= 300

    @pytest.mark.asyncio
    async def test_anchor_retry_over_limit_gets_trimmed(self, sample_document):
        """Regression: anchor rescue returning >45 words / >300 chars must be normalized."""
        with patch("services.writing.service.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                openrouter_api_key="test-key",
                writing_model="mistralai/mistral-medium-3.1",
                writing_model_linkedin_connection="",
                pea_selector_enabled=False,
                writing_relevance_gate_enabled=False,
            )

            # First response: no company anchor (>= 20 words)
            first_msg = MagicMock()
            first_msg.choices = [MagicMock()]
            first_msg.choices[0].message.content = (
                "Message:\n"
                "Your team is scaling fast and the data layer challenges usually surface at this stage "
                "when traffic climbs. Curious how you're handling that?"
            )
            first_msg.usage = None

            # Anchor rescue returns 51 words and >300 chars
            filler = " ".join(["growth"] * 40)
            rescue_text = f"Acme Corp is scaling. {filler} Curious about that?"
            assert len(rescue_text.split()) > 45
            assert len(rescue_text) > 300

            anchor_resp = MagicMock()
            anchor_resp.choices = [MagicMock()]
            anchor_resp.choices[0].message.content = rescue_text
            anchor_resp.usage = None

            # CTA rescue after word-trim + char-trim (trim kills trailing ?)
            cta_rescue_text = "Acme Corp is scaling their data layer fast and the challenges usually surface at this stage. Curious how you're handling that?"
            cta_resp = MagicMock()
            cta_resp.choices = [MagicMock()]
            cta_resp.choices[0].message.content = cta_rescue_text
            cta_resp.usage = None

            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(
                side_effect=[first_msg, anchor_resp, cta_resp]
            )

            with patch("services.writing.service.AsyncOpenAI") as mock_openai:
                mock_openai.return_value = mock_client
                service = WritingService()
                result = await service.generate_linkedin_message(
                    document=sample_document,
                    product_context="MongoDB Atlas database",
                    linkedin_context={"content_type": "none", "low_confidence": True},
                    mode="connection_request",
                    problems_solved="database scalability",
                )

        assert result["word_count"] <= 45
        assert result["char_count"] <= 300
        assert result["message"].strip().endswith("?")

    @pytest.mark.asyncio
    async def test_model_override_used(self, sample_document):
        """Regression: WRITING_MODEL_LINKEDIN_CONNECTION must be used for connection_request mode."""
        with patch("services.writing.service.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                openrouter_api_key="test-key",
                writing_model="mistralai/mistral-medium-3.1",
                writing_model_linkedin_connection="anthropic/claude-sonnet",
                pea_selector_enabled=False,
                writing_relevance_gate_enabled=False,
            )

            mock_message = MagicMock()
            mock_message.choices = [MagicMock()]
            mock_message.choices[0].message.content = (
                "Message:\n"
                "Acme Corp's data growth and engineering expansion caught my eye. "
                "The companies at your stage usually hit a scaling inflection point. "
                "Curious how you're handling that?"
            )
            mock_message.usage = None

            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_message)

            with patch("services.writing.service.AsyncOpenAI") as mock_openai:
                mock_openai.return_value = mock_client
                service = WritingService()
                await service.generate_linkedin_message(
                    document=sample_document,
                    product_context="MongoDB Atlas database",
                    linkedin_context={"content_type": "none", "low_confidence": True},
                    mode="connection_request",
                    problems_solved="database scalability",
                )

        call_kwargs = mock_client.chat.completions.create.call_args_list[0].kwargs
        assert call_kwargs["model"] == "anthropic/claude-sonnet"


# --- LinkedIn channel modes (CR) ---


class TestLinkedInMinWordFloor:
    def test_under_20_words_cr(self, linkedin_cr_strategy):
        """CR messages under 20 words should fail validation."""
        msg = "Acme Corp looks great. Scaling?"
        assert len(msg.split()) < 20
        ctx = GenerationContext(document=None, product_context="", report="", company_name="Acme Corp")
        result = linkedin_cr_strategy.validate(msg, ctx)
        assert result.is_valid is False
        assert "minimum is 20" in result.error_reason


class TestLinkedInConnectionNoteFlag:
    @pytest.mark.asyncio
    async def test_connection_request_blocked_when_flag_off(self, sample_document):
        """Service raises SequenceValidationError when connection note flag is off."""
        with patch("services.writing.service.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                openrouter_api_key="test-key",
                writing_model="mistralai/mistral-medium-3.1",
                writing_model_linkedin_connection="",
                pea_selector_enabled=False,
                writing_relevance_gate_enabled=False,
                linkedin_connection_note_enabled=False,
            )

            with patch("services.writing.service.AsyncOpenAI"):
                service = WritingService()
                with pytest.raises(SequenceValidationError) as exc_info:
                    await service.generate_linkedin_message(
                        document=sample_document,
                        product_context="MongoDB Atlas database",
                        linkedin_context={"content_type": "none", "low_confidence": True},
                        mode="connection_request",
                        problems_solved="database scalability",
                    )

        assert exc_info.value.code == "connection_note_disabled"

    @pytest.mark.asyncio
    async def test_dm_not_blocked_when_connection_note_flag_off(self, sample_document):
        """DM mode is unaffected by connection note flag."""
        with patch("services.writing.service.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                openrouter_api_key="test-key",
                writing_model="mistralai/mistral-medium-3.1",
                writing_model_linkedin_dm="",
                pea_selector_enabled=False,
                writing_relevance_gate_enabled=False,
                linkedin_connection_note_enabled=False,
            )

            mock_message = MagicMock()
            mock_message.choices = [MagicMock()]
            mock_message.choices[0].message.content = (
                "Message:\n"
                "Acme Corp is scaling its engineering team rapidly while shipping new products to market. "
                "The companies growing at that pace usually find the data layer becomes "
                "the bottleneck before anyone expects it to cause real problems. "
                "Curious how you're handling the data layer?"
            )
            mock_message.usage = None

            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_message)

            with patch("services.writing.service.AsyncOpenAI") as mock_openai:
                mock_openai.return_value = mock_client
                service = WritingService()
                result = await service.generate_linkedin_message(
                    document=sample_document,
                    product_context="MongoDB Atlas database",
                    linkedin_context={"content_type": "none", "low_confidence": True},
                    mode="dm",
                    problems_solved="database scalability",
                )

        assert result["mode"] == "dm"


class TestLinkedInChannelModes:
    def test_cr_limit_45(self):
        assert LINKEDIN_WORD_LIMITS["connection_request"] == 45

    def test_invalid_mode_not_in_dict(self):
        assert "invalid" not in LINKEDIN_WORD_LIMITS
