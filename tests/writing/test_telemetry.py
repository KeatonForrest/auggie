"""Tests for structured telemetry emission."""

import logging
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from services.writing import WritingService
from services.writing.types import GenerationTelemetry


class TestTelemetryEmission:
    def test_telemetry_dataclass_defaults(self):
        tel = GenerationTelemetry()
        assert tel.channel == ""
        assert tel.model == ""
        assert tel.latency_ms == 0
        assert tel.retry_count == 0
        assert tel.input_tokens == 0
        assert tel.output_tokens == 0
        assert tel.parse_success is False
        assert tel.repair_attempted is False
        assert tel.repair_success is False
        assert tel.word_limit_pass is False
        assert tel.cta_rescued is False
        assert tel.relevance_reprompted is False

    def test_telemetry_channel_tag(self):
        tel = GenerationTelemetry(channel="email")
        assert tel.channel == "email"

    def test_emit_telemetry_logs(self, writing_service, caplog):
        tel = GenerationTelemetry(
            channel="email",
            model="test-model",
            latency_ms=150,
            word_limit_pass=True,
        )
        with caplog.at_level(logging.INFO, logger="services.writing.service"):
            writing_service._emit_telemetry(tel)
        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert "email generation" in record.message
        assert record.channel == "email"
        assert record.model == "test-model"
        assert record.latency_ms == 150

    @pytest.mark.asyncio
    async def test_email_generation_emits_telemetry(self, sample_document, caplog):
        with patch("services.writing.service.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                openrouter_api_key="test-key",
                writing_model="mistralai/mistral-medium-3.1",
                writing_model_email="",
                pea_selector_enabled=False,
                writing_relevance_gate_enabled=False,
            )

            mock_message = MagicMock()
            mock_message.choices = [MagicMock()]
            mock_message.choices[0].message.content = (
                "Subject 1: test\n\n"
                "Email 1:\nBody one.\n\n"
                "Email 2:\nBody two.\n\n"
                "Email 3:\nBody three."
            )
            mock_message.usage = None

            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_message)

            with patch("services.writing.service.AsyncOpenAI") as mock_openai:
                mock_openai.return_value = mock_client
                service = WritingService()

                with caplog.at_level(logging.INFO, logger="services.writing.service"):
                    await service.generate_email_sequence(sample_document, "Product X")

        # Find the telemetry log record
        tel_records = [r for r in caplog.records if "email generation" in r.message]
        assert len(tel_records) >= 1
        record = tel_records[0]
        assert record.channel == "email"
        assert record.latency_ms >= 0
        assert record.word_limit_pass is True

    @pytest.mark.asyncio
    async def test_linkedin_generation_emits_telemetry(self, sample_document, caplog):
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
                "Acme Corp is scaling fast. Curious how you're handling the data layer?"
            )
            mock_message.usage = None

            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_message)

            with patch("services.writing.service.AsyncOpenAI") as mock_openai:
                mock_openai.return_value = mock_client
                service = WritingService()

                with caplog.at_level(logging.INFO, logger="services.writing.service"):
                    await service.generate_linkedin_message(
                        document=sample_document,
                        product_context="MongoDB Atlas database",
                        linkedin_context={"content_type": "none", "low_confidence": True},
                        mode="dm",
                        problems_solved="database scalability",
                    )

        tel_records = [r for r in caplog.records if "linkedin_dm generation" in r.message]
        assert len(tel_records) >= 1
        record = tel_records[0]
        assert record.channel == "linkedin_dm"
        assert record.latency_ms >= 0
        assert record.word_limit_pass is True
