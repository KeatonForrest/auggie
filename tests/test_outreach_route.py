"""Tests for the POST /document/{doc_id}/outreach route."""

import io
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.writing import SequenceValidationError


@pytest.fixture
def mock_document():
    """Minimal document for outreach tests."""
    mock_doc = MagicMock()
    mock_doc.id = 1
    mock_doc.company_name = "Acme Corp"
    mock_doc.company_overview = "Enterprise software company."
    mock_doc.opportunity_score = 70
    mock_doc.business_problems = ""
    mock_doc.existential_data_points = ""
    mock_doc.before_scenario = ""
    mock_doc.pvp_seed = ""
    mock_doc.projects_initiatives = ""
    mock_doc.confirmed_tech_stack = ""
    mock_doc.hiring_signals = ""
    mock_doc.product_fit = "Good fit."
    mock_doc.talking_points = ""
    mock_doc.key_contacts = ""
    mock_doc.recommended_contacts = ""
    mock_doc.information_gaps = ""
    mock_doc.full_markdown = ""
    return mock_doc


class TestOutreachRoute:
    @pytest.mark.asyncio
    async def test_happy_path(self, authed_client, mock_document):
        """Successful generation returns emails and subject_options."""
        emails = [
            {"email_number": 1, "subject": "test", "body": "Body 1"},
            {"email_number": 2, "subject": "test", "body": "Body 2"},
            {"email_number": 3, "subject": "test", "body": "Body 3"},
        ]
        with patch("routes.research.get_document", new_callable=AsyncMock, return_value=mock_document), \
             patch("routes.research.writing_service") as mock_ws:
            mock_ws.generate_email_sequence = AsyncMock(return_value=(emails, ["test", "alt1", "alt2"]))
            mock_ws.format_emails_markdown = MagicMock(return_value="# Emails\n\nbody")

            resp = await authed_client.post("/document/1/outreach")

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert len(data["emails"]) == 3
        assert len(data["subject_options"]) == 3
        assert "markdown" in data

    @pytest.mark.asyncio
    async def test_validation_error_returns_422(self, authed_client, mock_document):
        """SequenceValidationError returns structured 422."""
        with patch("routes.research.get_document", new_callable=AsyncMock, return_value=mock_document), \
             patch("routes.research.writing_service") as mock_ws:
            mock_ws.generate_email_sequence = AsyncMock(
                side_effect=SequenceValidationError(
                    code="sequence_validation_failed",
                    message="Expected 3 emails, got 1",
                )
            )

            resp = await authed_client.post("/document/1/outreach")

        assert resp.status_code == 422
        data = resp.json()
        assert data["success"] is False
        assert data["error"]["code"] == "sequence_validation_failed"
        assert "Expected 3 emails" in data["error"]["message"]

    @pytest.mark.asyncio
    async def test_repair_failure_returns_422(self, authed_client, mock_document):
        """Repair failure returns structured 422 with repair code."""
        with patch("routes.research.get_document", new_callable=AsyncMock, return_value=mock_document), \
             patch("routes.research.writing_service") as mock_ws:
            mock_ws.generate_email_sequence = AsyncMock(
                side_effect=SequenceValidationError(
                    code="sequence_repair_failed",
                    message="Generated sequence failed validation after repair",
                )
            )

            resp = await authed_client.post("/document/1/outreach")

        assert resp.status_code == 422
        data = resp.json()
        assert data["error"]["code"] == "sequence_repair_failed"

    @pytest.mark.asyncio
    async def test_generic_error_returns_500(self, authed_client, mock_document):
        """Unexpected exception returns structured 500."""
        with patch("routes.research.get_document", new_callable=AsyncMock, return_value=mock_document), \
             patch("routes.research.writing_service") as mock_ws:
            mock_ws.generate_email_sequence = AsyncMock(
                side_effect=RuntimeError("API timeout")
            )

            resp = await authed_client.post("/document/1/outreach")

        assert resp.status_code == 500
        data = resp.json()
        assert data["success"] is False
        assert data["error"]["code"] == "outreach_generation_failed"

    @pytest.mark.asyncio
    async def test_missing_document_returns_404(self, authed_client):
        """Non-existent document returns 404."""
        with patch("routes.research.get_document", new_callable=AsyncMock, return_value=None):
            resp = await authed_client.post("/document/999/outreach")

        assert resp.status_code == 404


class TestOutreachScreenshot:
    @pytest.mark.asyncio
    async def test_screenshot_passes_persona_to_generation(self, authed_client, mock_document):
        """Valid screenshot triggers persona extraction and passes context to generation."""
        emails = [
            {"email_number": 1, "subject": "test", "body": "Body 1"},
            {"email_number": 2, "subject": "test", "body": "Body 2"},
            {"email_number": 3, "subject": "test", "body": "Body 3"},
        ]
        fake_persona = {"name": "Jane Smith", "title": "VP Engineering"}

        with patch("routes.research.get_document", new_callable=AsyncMock, return_value=mock_document), \
             patch("routes.research.writing_service") as mock_ws, \
             patch("routes.research.vision_service") as mock_vs:
            mock_vs.extract_persona_from_screenshot = AsyncMock(return_value=fake_persona)
            mock_vs.format_persona_for_prompt = MagicMock(return_value="**Name:** Jane Smith\n**Title:** VP Engineering")
            mock_ws.generate_email_sequence = AsyncMock(return_value=(emails, ["test"]))
            mock_ws.format_emails_markdown = MagicMock(return_value="# Emails")

            # Upload a small PNG-like file
            png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
            resp = await authed_client.post(
                "/document/1/outreach",
                files={"screenshot": ("profile.png", io.BytesIO(png_bytes), "image/png")},
            )

        assert resp.status_code == 200
        # Verify persona_context was passed through
        call_kwargs = mock_ws.generate_email_sequence.call_args.kwargs
        assert "Jane Smith" in call_kwargs.get("persona_context", "")

    @pytest.mark.asyncio
    async def test_screenshot_extraction_failure_is_nonfatal(self, authed_client, mock_document):
        """Screenshot extraction failure doesn't block generation."""
        emails = [
            {"email_number": 1, "subject": "test", "body": "Body 1"},
            {"email_number": 2, "subject": "test", "body": "Body 2"},
            {"email_number": 3, "subject": "test", "body": "Body 3"},
        ]

        with patch("routes.research.get_document", new_callable=AsyncMock, return_value=mock_document), \
             patch("routes.research.writing_service") as mock_ws, \
             patch("routes.research.vision_service") as mock_vs:
            mock_vs.extract_persona_from_screenshot = AsyncMock(side_effect=RuntimeError("Vision API down"))
            mock_ws.generate_email_sequence = AsyncMock(return_value=(emails, ["test"]))
            mock_ws.format_emails_markdown = MagicMock(return_value="# Emails")

            png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
            resp = await authed_client.post(
                "/document/1/outreach",
                files={"screenshot": ("profile.png", io.BytesIO(png_bytes), "image/png")},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        # persona_context should be empty since extraction failed
        call_kwargs = mock_ws.generate_email_sequence.call_args.kwargs
        assert call_kwargs.get("persona_context", "") == ""

    @pytest.mark.asyncio
    async def test_oversized_screenshot_skipped(self, authed_client, mock_document):
        """Screenshot over 10MB is silently skipped."""
        emails = [
            {"email_number": 1, "subject": "test", "body": "Body 1"},
            {"email_number": 2, "subject": "test", "body": "Body 2"},
            {"email_number": 3, "subject": "test", "body": "Body 3"},
        ]

        with patch("routes.research.get_document", new_callable=AsyncMock, return_value=mock_document), \
             patch("routes.research.writing_service") as mock_ws, \
             patch("routes.research.vision_service") as mock_vs:
            mock_ws.generate_email_sequence = AsyncMock(return_value=(emails, ["test"]))
            mock_ws.format_emails_markdown = MagicMock(return_value="# Emails")

            # 11MB file
            big_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * (11 * 1024 * 1024)
            resp = await authed_client.post(
                "/document/1/outreach",
                files={"screenshot": ("big.png", io.BytesIO(big_bytes), "image/png")},
            )

        assert resp.status_code == 200
        # Vision service should never be called for oversized files
        mock_vs.extract_persona_from_screenshot.assert_not_called()
