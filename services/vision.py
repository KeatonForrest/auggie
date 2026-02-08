"""vision.py - Extract persona info from LinkedIn screenshots using vision models."""

import base64
import logging
import re
from openai import AsyncOpenAI

from config import get_settings

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT = """Extract the following information from this LinkedIn profile screenshot. Only extract what is clearly visible — do not guess or infer missing fields.

Output in this exact format (leave blank if not visible):

NAME: [full name]
TITLE: [current job title]
COMPANY: [current company]
HEADLINE: [LinkedIn headline]
ABOUT: [about/summary section, first 200 characters]
EXPERIENCE: [most recent 2-3 roles, formatted as "Title at Company (dates)"]
SKILLS: [top skills if visible, comma-separated]

If this is not a LinkedIn profile screenshot, respond with:
NOT_LINKEDIN: [brief description of what the image shows]"""


class VisionService:
    """Service for extracting structured data from screenshots using vision models."""

    def __init__(self):
        self.settings = get_settings()
        self.client = AsyncOpenAI(
            api_key=self.settings.openrouter_api_key,
            base_url="https://openrouter.ai/api/v1",
            timeout=30.0,
        )

    async def extract_persona_from_screenshot(
        self, image_bytes: bytes, content_type: str
    ) -> dict:
        """Extract structured persona info from a LinkedIn screenshot.

        Returns dict with keys: name, title, company, headline, about, experience, skills.
        Returns empty dict if extraction fails or image is not a LinkedIn profile.
        """
        b64_image = base64.b64encode(image_bytes).decode("utf-8")
        data_url = f"data:{content_type};base64,{b64_image}"

        try:
            response = await self.client.chat.completions.create(
                model=self.settings.vision_model,
                max_tokens=1000,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": EXTRACTION_PROMPT},
                            {"type": "image_url", "image_url": {"url": data_url}},
                        ],
                    }
                ],
            )

            text = response.choices[0].message.content or ""
            return self._parse_persona(text)

        except Exception as e:
            logger.error("Vision extraction failed: %s", e)
            return {}

    def _parse_persona(self, text: str) -> dict:
        """Parse the model's structured output into a dict."""
        if "NOT_LINKEDIN" in text:
            logger.info("Image is not a LinkedIn profile: %s", text[:200])
            return {}

        persona = {}
        field_map = {
            "NAME": "name",
            "TITLE": "title",
            "COMPANY": "company",
            "HEADLINE": "headline",
            "ABOUT": "about",
            "EXPERIENCE": "experience",
            "SKILLS": "skills",
        }

        for label, key in field_map.items():
            match = re.search(rf"^{label}:[ \t]*(.+)", text, re.MULTILINE)
            if match:
                value = match.group(1).strip()
                if value and value.lower() not in ("n/a", "not visible", "blank"):
                    persona[key] = value

        return persona

    def format_persona_for_prompt(self, persona: dict) -> str:
        """Format extracted persona info for inclusion in the writing prompt."""
        if not persona:
            return ""

        lines = []
        if persona.get("name"):
            lines.append(f"**Name:** {persona['name']}")
        if persona.get("title"):
            lines.append(f"**Title:** {persona['title']}")
        if persona.get("company"):
            lines.append(f"**Company:** {persona['company']}")
        if persona.get("headline"):
            lines.append(f"**Headline:** {persona['headline']}")
        if persona.get("about"):
            lines.append(f"**About:** {persona['about']}")
        if persona.get("experience"):
            lines.append(f"**Experience:** {persona['experience']}")
        if persona.get("skills"):
            lines.append(f"**Skills:** {persona['skills']}")

        return "\n".join(lines)
