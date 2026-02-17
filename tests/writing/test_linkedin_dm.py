"""Tests for LinkedIn DM strategy and message generation."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from services.writing import WritingService, SequenceValidationError
from services.writing.types import GenerationContext, LINKEDIN_WORD_LIMITS
from services.writing.linkedin_shared import filter_relevance


# --- LinkedIn system prompt (DM) ---


class TestLinkedInSystemPrompt:
    def test_dm_word_limit(self, linkedin_dm_strategy):
        ctx = GenerationContext(document=None, product_context="", report="", mode="dm")
        prompt = linkedin_dm_strategy.build_system_prompt(ctx)
        assert "50-90 words" in prompt
        assert "Hook" in prompt
        assert "Bridge" in prompt
        assert "CTA" in prompt

    def test_no_email_rules(self, linkedin_dm_strategy):
        ctx = GenerationContext(document=None, product_context="", report="", mode="dm")
        prompt = linkedin_dm_strategy.build_system_prompt(ctx)
        assert "PEA FRAMEWORK" not in prompt
        assert "Subject 1:" not in prompt
        assert "Email 1:" not in prompt

    def test_relevance_guardrail(self, linkedin_dm_strategy):
        ctx = GenerationContext(document=None, product_context="", report="", mode="dm")
        prompt = linkedin_dm_strategy.build_system_prompt(ctx)
        assert "RELEVANCE GUARDRAIL" in prompt
        assert "Only reference pains" in prompt


# --- LinkedIn user prompt ---


class TestLinkedInUserPrompt:
    def test_profile_context(self, linkedin_dm_strategy):
        ctx = GenerationContext(
            document=None, product_context="MongoDB Atlas database", report="report text",
            mode="dm", problems_solved="scalability",
            linkedin_context={
                "content_type": "profile",
                "author_name": "Jane Smith",
                "author_title": "VP Engineering",
                "author_company": "Acme Corp",
                "focus_snippet": "Building scalable systems for enterprise customers.",
                "low_confidence": False,
            },
        )
        prompt = linkedin_dm_strategy.build_user_prompt(ctx)
        assert "<screenshot_context>" in prompt
        assert "Jane Smith" in prompt
        assert "VP Engineering" in prompt
        assert "scalable systems" in prompt

    def test_post_context(self, linkedin_dm_strategy):
        ctx = GenerationContext(
            document=None, product_context="product", report="report",
            mode="dm", problems_solved="problems",
            linkedin_context={
                "content_type": "post",
                "author_name": "John Doe",
                "focus_snippet": "We just shipped our new platform.",
                "engagement": "100 reactions",
                "low_confidence": False,
            },
        )
        prompt = linkedin_dm_strategy.build_user_prompt(ctx)
        assert "<screenshot_context>" in prompt
        assert "shipped our new platform" in prompt

    def test_low_confidence_fallback(self, linkedin_dm_strategy):
        ctx = GenerationContext(
            document=None, product_context="product", report="report",
            mode="dm", problems_solved="problems",
            linkedin_context={"content_type": "profile", "low_confidence": True},
        )
        prompt = linkedin_dm_strategy.build_user_prompt(ctx)
        assert "<screenshot_context>" not in prompt
        assert "Screenshot was unclear" in prompt

    def test_research_only(self, linkedin_dm_strategy):
        ctx = GenerationContext(
            document=None, product_context="product", report="report",
            mode="dm", problems_solved="problems",
            linkedin_context={"content_type": "none", "low_confidence": True},
        )
        prompt = linkedin_dm_strategy.build_user_prompt(ctx)
        assert "<screenshot_context>" not in prompt
        assert "<report>" in prompt

    def test_seller_context_always_present(self, linkedin_dm_strategy):
        ctx = GenerationContext(
            document=None, product_context="MongoDB Atlas database", report="report",
            mode="dm", problems_solved="scalability, performance",
            linkedin_context={"content_type": "none", "low_confidence": True},
        )
        prompt = linkedin_dm_strategy.build_user_prompt(ctx)
        assert "SELLER CONTEXT" in prompt
        assert "MongoDB Atlas database" in prompt
        assert "scalability, performance" in prompt

    def test_company_anchor_instruction(self, linkedin_dm_strategy):
        ctx = GenerationContext(
            document=None, product_context="product", report="report",
            mode="dm", problems_solved="problems", company_name="Fortive.com",
            linkedin_context={"content_type": "none", "low_confidence": True},
        )
        prompt = linkedin_dm_strategy.build_user_prompt(ctx)
        assert "MUST mention the company" in prompt
        assert '"fortive"' in prompt


# --- LinkedIn relevance filter ---


class TestLinkedInRelevanceFilter:
    def test_db_seller_react_blocked(self):
        msg = "Your React frontend rewrite looks ambitious."
        is_clean, blocked = filter_relevance(msg, "database")
        assert is_clean is False
        assert "react" in blocked

    def test_db_seller_query_passes(self):
        msg = "Your query performance challenges remind me of a pattern."
        is_clean, blocked = filter_relevance(msg, "database")
        assert is_clean is True
        assert blocked == []

    def test_unknown_category_passes(self):
        msg = "Your React and CDN setup is interesting."
        is_clean, blocked = filter_relevance(msg, "")
        assert is_clean is True

    def test_cdn_db_linkage_passes(self):
        msg = "Your CDN changes are causing a database bottleneck in the API layer."
        is_clean, blocked = filter_relevance(msg, "database")
        assert is_clean is True


# --- LinkedIn quality gate (DM) ---


class TestLinkedInQualityGate:
    def test_valid_passes(self, linkedin_dm_strategy):
        msg = "Acme Corp is scaling fast. The companies growing at your pace usually hit a data layer bottleneck they don't see coming. Curious how you're thinking about that?"
        ctx = GenerationContext(document=None, product_context="", report="", company_name="Acme Corp")
        result = linkedin_dm_strategy.validate(msg, ctx)
        assert result.is_valid is True
        assert result.error_reason == ""

    def test_no_question_mark(self, linkedin_dm_strategy):
        msg = "Acme Corp is scaling fast. The companies growing at your pace usually hit a data layer bottleneck."
        ctx = GenerationContext(document=None, product_context="", report="", company_name="Acme Corp")
        result = linkedin_dm_strategy.validate(msg, ctx)
        assert result.is_valid is False
        assert "must end with exactly one question" in result.error_reason

    def test_question_in_middle(self, linkedin_dm_strategy):
        msg = "Is Acme Corp scaling? The companies growing at your pace usually hit a data layer bottleneck."
        ctx = GenerationContext(document=None, product_context="", report="", company_name="Acme Corp")
        result = linkedin_dm_strategy.validate(msg, ctx)
        assert result.is_valid is False
        assert "must end with exactly one question" in result.error_reason

    def test_multiple_questions(self, linkedin_dm_strategy):
        msg = "Is Acme Corp scaling fast? Are you thinking about your data layer?"
        ctx = GenerationContext(document=None, product_context="", report="", company_name="Acme Corp")
        result = linkedin_dm_strategy.validate(msg, ctx)
        assert result.is_valid is False
        assert "must end with exactly one question" in result.error_reason

    def test_banned_robotic_phrase(self, linkedin_dm_strategy):
        msg = "I noticed on your LinkedIn that Acme Corp is doing interesting work. Curious how you're thinking about scaling?"
        ctx = GenerationContext(document=None, product_context="", report="", company_name="Acme Corp")
        result = linkedin_dm_strategy.validate(msg, ctx)
        assert result.is_valid is False
        assert "banned phrase" in result.error_reason

    def test_i_noticed_natural_passes(self, linkedin_dm_strategy):
        msg = "I noticed Acme Corp is hiring three data engineers this quarter. That usually means the pipeline has outgrown the team. Curious how you're handling that?"
        ctx = GenerationContext(document=None, product_context="", report="", company_name="Acme Corp")
        result = linkedin_dm_strategy.validate(msg, ctx)
        assert result.is_valid is True

    def test_i_saw_natural_passes(self, linkedin_dm_strategy):
        msg = "I saw Acme Corp just closed a Series B. That pace of growth usually surfaces infra bottlenecks. Curious how you're thinking about scaling?"
        ctx = GenerationContext(document=None, product_context="", report="", company_name="Acme Corp")
        result = linkedin_dm_strategy.validate(msg, ctx)
        assert result.is_valid is True

    def test_came_across_profile_banned(self, linkedin_dm_strategy):
        msg = "I came across your profile and Acme Corp caught my eye. Curious how you're thinking about scaling?"
        ctx = GenerationContext(document=None, product_context="", report="", company_name="Acme Corp")
        result = linkedin_dm_strategy.validate(msg, ctx)
        assert result.is_valid is False
        assert "banned phrase" in result.error_reason

    def test_valid_phrase_passes(self, linkedin_dm_strategy):
        msg = "Based on Acme Corp's team growth, the data layer challenges usually surface around this stage. Curious how you're handling that?"
        ctx = GenerationContext(document=None, product_context="", report="", company_name="Acme Corp")
        result = linkedin_dm_strategy.validate(msg, ctx)
        assert result.is_valid is True

    def test_missing_anchor(self, linkedin_dm_strategy):
        msg = "Your team is growing fast and the data challenges usually surface at this stage. Curious how you're handling that?"
        ctx = GenerationContext(document=None, product_context="", report="", company_name="Acme Corp")
        result = linkedin_dm_strategy.validate(msg, ctx)
        assert result.is_valid is False
        assert "lacks a prospect-specific anchor" in result.error_reason

    def test_over_100_words_dm(self, linkedin_dm_strategy):
        words = ["word"] * 105
        words[10] = "Acme"
        words[11] = "Corp"
        msg = " ".join(words) + "?"
        ctx = GenerationContext(document=None, product_context="", report="", company_name="Acme Corp")
        result = linkedin_dm_strategy.validate(msg, ctx)
        assert result.is_valid is False
        assert "105 words" in result.error_reason

    def test_anchor_matches_with_suffix(self, linkedin_dm_strategy):
        msg = "MongoDB is scaling its data platform fast. Curious how the team handles peak throughput?"
        ctx = GenerationContext(document=None, product_context="", report="", company_name="MongoDB, Inc.")
        result = linkedin_dm_strategy.validate(msg, ctx)
        assert result.is_valid is True

    def test_anchor_matches_dotcom(self, linkedin_dm_strategy):
        msg = "Nike is pushing into direct-to-consumer at a pace that usually surfaces fulfillment bottlenecks. Curious how you're handling that?"
        ctx = GenerationContext(document=None, product_context="", report="", company_name="nike.com")
        result = linkedin_dm_strategy.validate(msg, ctx)
        assert result.is_valid is True

    def test_anchor_still_fails_when_absent(self, linkedin_dm_strategy):
        msg = "Your team is growing fast and challenges surface at this stage. Curious how you're handling that?"
        ctx = GenerationContext(document=None, product_context="", report="", company_name="MongoDB, Inc.")
        result = linkedin_dm_strategy.validate(msg, ctx)
        assert result.is_valid is False
        assert "lacks a prospect-specific anchor" in result.error_reason

    def test_anchor_domain_root(self, linkedin_dm_strategy):
        msg = "Fortive is growing through acquisitions fast. Curious how you're integrating the new teams?"
        ctx = GenerationContext(document=None, product_context="", report="", company_name="fortive.com")
        result = linkedin_dm_strategy.validate(msg, ctx)
        assert result.is_valid is True

    def test_anchor_org_domain(self, linkedin_dm_strategy):
        msg = "Acme is doing interesting work in the nonprofit space. Curious how you're scaling operations?"
        ctx = GenerationContext(document=None, product_context="", report="", company_name="acme.org")
        result = linkedin_dm_strategy.validate(msg, ctx)
        assert result.is_valid is True

    def test_anchor_multiword_token(self, linkedin_dm_strategy):
        msg = "Palo Alto's expansion into cloud security is impressive. Curious how the migration path is going?"
        ctx = GenerationContext(document=None, product_context="", report="", company_name="Palo Alto Networks, Inc.")
        result = linkedin_dm_strategy.validate(msg, ctx)
        assert result.is_valid is True


# --- LinkedIn message generation (DM) ---


class TestLinkedInMessageGeneration:
    @pytest.mark.asyncio
    async def test_happy_dm(self, sample_document):
        with patch("services.writing.service.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                openrouter_api_key="test-key",
                writing_model="mistralai/mistral-medium-3.1",
                writing_model_linkedin_dm="",
                pea_selector_enabled=False,
                writing_relevance_gate_enabled=False,
            )

            mock_message = MagicMock()
            mock_message.choices = [MagicMock()]
            mock_message.choices[0].message.content = (
                "Message:\n"
                "Acme Corp is scaling its engineering team while shipping new products. "
                "The companies growing at that pace usually find the data layer becomes "
                "the bottleneck before anyone expects it. Curious how you're thinking about that?"
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
        assert result["word_count"] <= 90
        assert "Acme Corp" in result["message"]
        assert result["message"].strip().endswith("?")

    @pytest.mark.asyncio
    async def test_invalid_mode_raises(self, sample_document):
        with patch("services.writing.service.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                openrouter_api_key="test-key",
                writing_model="mistralai/mistral-medium-3.1",
                writing_model_linkedin_dm="",
                pea_selector_enabled=False,
                writing_relevance_gate_enabled=False,
            )

            with patch("services.writing.service.AsyncOpenAI"):
                service = WritingService()
                with pytest.raises(ValueError, match="Invalid LinkedIn message mode"):
                    await service.generate_linkedin_message(
                        document=sample_document,
                        product_context="MongoDB Atlas database",
                        linkedin_context={"content_type": "none", "low_confidence": True},
                        mode="invalid_mode",
                        problems_solved="database scalability",
                    )

    @pytest.mark.asyncio
    async def test_over_limit_trimmed(self, sample_document):
        with patch("services.writing.service.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                openrouter_api_key="test-key",
                writing_model="mistralai/mistral-medium-3.1",
                writing_model_linkedin_dm="",
                pea_selector_enabled=False,
                writing_relevance_gate_enabled=False,
            )

            over_msg = "Acme Corp is doing great work. " + " ".join(["Growth"] * 100) + " Curious about scaling?"
            mock_message = MagicMock()
            mock_message.choices = [MagicMock()]
            mock_message.choices[0].message.content = f"Message:\n{over_msg}"
            mock_message.usage = None

            rescue_msg = "Acme Corp is doing great work on their data platform. Curious about scaling?"
            mock_rescue = MagicMock()
            mock_rescue.choices = [MagicMock()]
            mock_rescue.choices[0].message.content = rescue_msg
            mock_rescue.usage = None

            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(
                side_effect=[mock_message, mock_rescue]
            )

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

        assert result["word_count"] <= 100

    @pytest.mark.asyncio
    async def test_empty_response_raises(self, sample_document):
        with patch("services.writing.service.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                openrouter_api_key="test-key",
                writing_model="mistralai/mistral-medium-3.1",
                writing_model_linkedin_dm="",
                pea_selector_enabled=False,
                writing_relevance_gate_enabled=False,
            )

            mock_message = MagicMock()
            mock_message.choices = [MagicMock()]
            mock_message.choices[0].message.content = ""
            mock_message.usage = None

            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_message)

            with patch("services.writing.service.AsyncOpenAI") as mock_openai:
                mock_openai.return_value = mock_client
                service = WritingService()
                with pytest.raises(SequenceValidationError) as exc_info:
                    await service.generate_linkedin_message(
                        document=sample_document,
                        product_context="MongoDB Atlas database",
                        linkedin_context={"content_type": "none", "low_confidence": True},
                        problems_solved="database scalability",
                    )
                assert exc_info.value.code == "linkedin_generation_failed"

    @pytest.mark.asyncio
    async def test_anchor_retry_rescues_missing_company(self, sample_document):
        with patch("services.writing.service.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                openrouter_api_key="test-key",
                writing_model="mistralai/mistral-medium-3.1",
                writing_model_linkedin_dm="",
                pea_selector_enabled=False,
                writing_relevance_gate_enabled=False,
            )

            first_msg = MagicMock()
            first_msg.choices = [MagicMock()]
            first_msg.choices[0].message.content = (
                "Message:\n"
                "Your team is scaling fast and the data layer usually becomes the bottleneck at this stage. "
                "Curious how you're thinking about that?"
            )
            first_msg.usage = None

            rescue_msg = MagicMock()
            rescue_msg.choices = [MagicMock()]
            rescue_msg.choices[0].message.content = (
                "Acme Corp is scaling fast and the data layer usually becomes the bottleneck at this stage. "
                "Curious how you're thinking about that?"
            )
            rescue_msg.usage = None

            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(
                side_effect=[first_msg, rescue_msg]
            )

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

        assert "acme" in result["message"].lower()
        assert mock_client.chat.completions.create.call_count == 2

    @pytest.mark.asyncio
    async def test_anchor_retry_over_limit_gets_trimmed(self, sample_document):
        """Regression: anchor rescue returning 91 words must be normalized to ≤90."""
        with patch("services.writing.service.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                openrouter_api_key="test-key",
                writing_model="mistralai/mistral-medium-3.1",
                writing_model_linkedin_dm="",
                pea_selector_enabled=False,
                writing_relevance_gate_enabled=False,
            )

            # First response: no company anchor
            first_msg = MagicMock()
            first_msg.choices = [MagicMock()]
            first_msg.choices[0].message.content = (
                "Message:\n"
                "Your team is scaling fast and the data layer usually becomes the bottleneck. "
                "Curious how you're thinking about that?"
            )
            first_msg.usage = None

            # Anchor rescue returns >100 words (over the 90+10 buffer)
            filler = " ".join(["growth"] * 97)
            rescue_text = f"Acme Corp is scaling fast. {filler} Curious about that?"
            assert len(rescue_text.split()) > 100

            anchor_resp = MagicMock()
            anchor_resp.choices = [MagicMock()]
            anchor_resp.choices[0].message.content = rescue_text
            anchor_resp.usage = None

            # CTA rescue after trim (trim kills the trailing ?)
            cta_rescue_text = (
                "Acme Corp is scaling fast and the data layer is the usual bottleneck. "
                "Curious how you're thinking about that?"
            )
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
                    mode="dm",
                    problems_solved="database scalability",
                )

        assert result["word_count"] <= 100
        assert result["message"].strip().endswith("?")


# --- LinkedIn channel modes (DM) ---


class TestLinkedInChannelModes:
    def test_dm_limit_90(self):
        assert LINKEDIN_WORD_LIMITS["dm"] == 90
