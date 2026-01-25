"""writing.py - AI-powered outreach generation using Claude Sonnet."""

import anthropic
import re
from typing import Optional
from models import ResearchDocument
from config import get_settings


class WritingService:
    """Service for generating outreach emails from research documents."""

    def __init__(self):
        self.settings = get_settings()
        self.client = anthropic.Anthropic(api_key=self.settings.anthropic_api_key)

    def _build_report(self, document: ResearchDocument, product_context: str) -> str:
        """Build the report content from research document."""
        sections = []

        sections.append(f"# Research Report: {document.company_name}")
        sections.append("")

        sections.append("## Company Overview")
        sections.append(document.company_overview)
        sections.append("")

        if document.business_problems:
            sections.append("## Business Problems & Pain Points")
            sections.append(document.business_problems)
            sections.append("")

        if document.projects_initiatives:
            sections.append("## Current Projects & Initiatives")
            sections.append(document.projects_initiatives)
            sections.append("")

        if document.confirmed_tech_stack:
            sections.append("## Technology Stack")
            sections.append(document.confirmed_tech_stack)
            sections.append("")

        if document.product_fit:
            sections.append("## Product Fit Analysis")
            sections.append(document.product_fit)
            sections.append("")

        if document.talking_points:
            sections.append("## Recommended Talking Points")
            sections.append(document.talking_points)
            sections.append("")

        if document.key_contacts:
            sections.append("## Key Contacts")
            sections.append(document.key_contacts)
            sections.append("")

        sections.append("## Our Product (What We're Selling)")
        sections.append(product_context)

        return "\n".join(sections)

    def _build_prompt(self, report: str) -> str:
        """Build the full prompt with the report inserted."""
        return f"""You are an expert at converting research into a series of informative and emotionally engaging emails.

Your task is to take research content and transform it into three separate emails that can be sent over multiple touches. The purpose of these emails is to explain what problem is being solved and how it is fixed.

Here is the research content you will be working with:

<report>
{report}
</report>

Your goal is to create three distinct emails based on this research. Each email should focus on a different aspect of the problem and solution, while maintaining a cohesive narrative across all three.

Follow these guidelines for each email:

**First Email:**
- Introduce the problem and create emotional resonance
- Highlight the pain points and challenges faced by the audience
- Hint at the solution without fully revealing it
- Keep it concise, around 100 words
- Include a compelling subject line

**Second Email:**
- Dive deeper into the problem and its implications
- Begin to introduce the solution and its benefits
- Use storytelling elements to maintain engagement
- Aim for 100 words
- Include a compelling subject line

**Third Email:**
- Fully explain the solution and how it addresses the problem
- Emphasize the unique value proposition
- Include a clear call-to-action
- Keep it impactful, around 75 words
- Include a compelling subject line

**General Guidelines for All Emails:**
- Use a formal yet approachable professional tone
- Incorporate emotional triggers to create a connection with the reader
- Break up text into short paragraphs for easy readability
- Use bullet points or numbered lists where appropriate
- Maintain consistency across all three emails while progressively building on the information and emotional engagement
- NEVER use emdashes (—) in any of the emails - use commas, periods, or separate sentences instead

Present your final output in the following format:

<email_series>
<email1>
Subject: [Insert subject line]

[Insert body of first email]
</email1>

<email2>
Subject: [Insert subject line]

[Insert body of second email]
</email2>

<email3>
Subject: [Insert subject line]

[Insert body of third email]
</email3>
</email_series>

Your goal is to create a compelling narrative that explains the problem, builds anticipation for the solution, and ultimately convinces the reader of its value."""

    def _parse_emails(self, response: str) -> list[dict]:
        """Parse the email series from the response."""
        emails = []

        # Extract each email block
        for i in range(1, 4):
            pattern = f"<email{i}>(.*?)</email{i}>"
            match = re.search(pattern, response, re.DOTALL)

            if match:
                content = match.group(1).strip()

                # Extract subject line
                subject_match = re.search(r"Subject:\s*(.+?)(?:\n|$)", content)
                subject = subject_match.group(1).strip() if subject_match else f"Email {i}"

                # Extract body (everything after subject line)
                body = re.sub(r"Subject:\s*.+?\n", "", content, count=1).strip()

                emails.append({
                    "email_number": i,
                    "subject": subject,
                    "body": body
                })

        return emails

    async def generate_email_sequence(
        self,
        document: ResearchDocument,
        product_context: str,
    ) -> list[dict]:
        """Generate a 3-email sequence from a research document."""

        # Build the report from research
        report = self._build_report(document, product_context)

        # Build the full prompt
        prompt = self._build_prompt(report)

        # Call Sonnet
        message = self.client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}]
        )

        response = message.content[0].text

        # Parse the emails
        emails = self._parse_emails(response)

        return emails

    def format_emails_markdown(self, emails: list[dict]) -> str:
        """Format emails as markdown for display."""
        sections = ["# Email Sequence"]

        for email in emails:
            # Convert single newlines in body to double newlines for proper paragraph spacing
            body_with_spacing = email['body'].replace('\n', '\n\n')

            sections.append(f"## Email {email['email_number']}")
            sections.append(f"**Subject:** {email['subject']}")
            sections.append(body_with_spacing)
            sections.append("---")

        return "\n\n".join(sections)
