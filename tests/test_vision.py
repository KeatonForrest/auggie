"""Tests for VisionService: persona extraction from LinkedIn screenshots."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from services.vision import VisionService


@pytest.fixture
def vision_service():
    """VisionService with mocked API client."""
    with patch("services.vision.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(
            openrouter_api_key="test-key",
            vision_model="anthropic/claude-sonnet-4",
        )
        with patch("services.vision.AsyncOpenAI"):
            service = VisionService()
    return service


# --- _parse_persona ---


class TestParsPersona:
    def test_parses_complete_output(self, vision_service):
        text = (
            "NAME: Jane Smith\n"
            "TITLE: VP of Engineering\n"
            "COMPANY: Acme Corp\n"
            "HEADLINE: Building scalable systems at Acme\n"
            "ABOUT: Passionate about distributed systems and team building.\n"
            "EXPERIENCE: VP Engineering at Acme Corp (2022-present), Senior Engineer at BigCo (2019-2022)\n"
            "SKILLS: Python, Kubernetes, System Design"
        )
        persona = vision_service._parse_persona(text)
        assert persona["name"] == "Jane Smith"
        assert persona["title"] == "VP of Engineering"
        assert persona["company"] == "Acme Corp"
        assert persona["headline"] == "Building scalable systems at Acme"
        assert "distributed systems" in persona["about"]
        assert "VP Engineering" in persona["experience"]
        assert "Python" in persona["skills"]

    def test_parses_partial_output(self, vision_service):
        text = "NAME: John Doe\nTITLE: CTO\nCOMPANY: StartupX\n"
        persona = vision_service._parse_persona(text)
        assert persona["name"] == "John Doe"
        assert persona["title"] == "CTO"
        assert persona["company"] == "StartupX"
        assert "headline" not in persona
        assert "about" not in persona

    def test_returns_empty_for_non_linkedin(self, vision_service):
        text = "NOT_LINKEDIN: This appears to be a screenshot of a spreadsheet."
        persona = vision_service._parse_persona(text)
        assert persona == {}

    def test_skips_blank_fields(self, vision_service):
        text = "NAME: Jane Doe\nTITLE: \nCOMPANY: n/a\nHEADLINE: Not visible"
        persona = vision_service._parse_persona(text)
        assert persona["name"] == "Jane Doe"
        assert "title" not in persona
        assert "company" not in persona
        assert "headline" not in persona


# --- format_persona_for_prompt ---


class TestFormatPersonaForPrompt:
    def test_formats_complete_persona(self, vision_service):
        persona = {
            "name": "Jane Smith",
            "title": "VP of Engineering",
            "company": "Acme Corp",
            "headline": "Building scalable systems",
        }
        result = vision_service.format_persona_for_prompt(persona)
        assert "**Name:** Jane Smith" in result
        assert "**Title:** VP of Engineering" in result
        assert "**Company:** Acme Corp" in result
        assert "**Headline:** Building scalable systems" in result

    def test_formats_partial_persona(self, vision_service):
        persona = {"name": "John", "title": "CTO"}
        result = vision_service.format_persona_for_prompt(persona)
        assert "**Name:** John" in result
        assert "**Title:** CTO" in result
        assert "Company" not in result

    def test_empty_persona_returns_empty_string(self, vision_service):
        assert vision_service.format_persona_for_prompt({}) == ""


# --- extract_persona_from_screenshot ---


class TestExtractPersona:
    @pytest.mark.asyncio
    async def test_successful_extraction(self):
        with patch("services.vision.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                openrouter_api_key="test-key",
                vision_model="anthropic/claude-sonnet-4",
            )

            mock_message = MagicMock()
            mock_message.choices = [MagicMock()]
            mock_message.choices[0].message.content = (
                "NAME: Jane Smith\nTITLE: VP Engineering\nCOMPANY: Acme"
            )

            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_message)

            with patch("services.vision.AsyncOpenAI") as mock_openai:
                mock_openai.return_value = mock_client
                service = VisionService()
                persona = await service.extract_persona_from_screenshot(
                    b"fake-image-bytes", "image/png"
                )

        assert persona["name"] == "Jane Smith"
        assert persona["title"] == "VP Engineering"

        # Verify the API call included the image
        call_args = mock_client.chat.completions.create.call_args
        content = call_args.kwargs["messages"][0]["content"]
        assert any(item.get("type") == "image_url" for item in content)

    @pytest.mark.asyncio
    async def test_api_error_returns_empty(self):
        with patch("services.vision.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                openrouter_api_key="test-key",
                vision_model="anthropic/claude-sonnet-4",
            )

            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(
                side_effect=RuntimeError("API error")
            )

            with patch("services.vision.AsyncOpenAI") as mock_openai:
                mock_openai.return_value = mock_client
                service = VisionService()
                persona = await service.extract_persona_from_screenshot(
                    b"fake-image-bytes", "image/png"
                )

        assert persona == {}

    @pytest.mark.asyncio
    async def test_non_linkedin_image_returns_empty(self):
        with patch("services.vision.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                openrouter_api_key="test-key",
                vision_model="anthropic/claude-sonnet-4",
            )

            mock_message = MagicMock()
            mock_message.choices = [MagicMock()]
            mock_message.choices[0].message.content = (
                "NOT_LINKEDIN: This is a screenshot of a company website."
            )

            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_message)

            with patch("services.vision.AsyncOpenAI") as mock_openai:
                mock_openai.return_value = mock_client
                service = VisionService()
                persona = await service.extract_persona_from_screenshot(
                    b"fake-image-bytes", "image/png"
                )

        assert persona == {}
