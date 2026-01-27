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
        return f"""You are an expert at crafting Personalized Value Propositions (PVPs) - messages so valuable that prospects would pay to receive them, even if they never buy your product.

A PVP uses publicly available data to deliver insights that directly impact the prospect's business. Unlike traditional feature-focused outreach, a PVP leads with concrete, actionable intelligence that demonstrates you understand their specific situation.

Here is the research content you will be working with:

<report>
{report}
</report>

Your goal is to create three distinct PVP emails based on this research. Each email should deliver genuine, standalone value - not just a clever way to pitch a product.

**Types of Value to Deliver (use the research to identify which applies):**
- **Cost savings opportunity**: "We noticed X technology in your stack typically costs Y% more than Z alternative"
- **Risk mitigation**: "Your job posting mentions using [deprecated technology] - here's the migration timeline before support ends"
- **Revenue opportunity**: "Companies with your tech stack typically see X% improvement when they address [specific gap]"
- **Competitive intelligence**: "Three of your competitors recently adopted X - here's what they're doing differently"
- **Efficiency gains**: "Your team is hiring for X role to solve Y problem - here's a faster approach"
- **Market timing**: "Based on your tech stack and hiring, you're likely hitting Z scaling challenge right now"

**First Email - Lead with a Specific Insight:**
- Open with a concrete observation from their tech stack, hiring, or public data
- Deliver one actionable insight they can use immediately
- The insight should be valuable even if they ignore your product entirely
- Keep it concise, around 100 words
- Include a subject line that hints at the specific insight

**Second Email - Deepen the Value:**
- Build on the first insight with additional context or data
- Reference patterns from similar companies (industry, stage, tech stack)
- Provide a framework, checklist, or specific recommendation they can act on
- Aim for 100 words
- Include a subject line that promises concrete value

**Third Email - Connect Value to Conversation:**
- Summarize the insights you've shared
- Now (and only now) briefly mention how your product relates to what you've discussed
- Include a soft call-to-action focused on continuing the conversation, not closing a sale
- Keep it impactful, around 75 words
- Include a subject line

**Critical Guidelines:**
- The prospect should thank you for these emails even if they never become a customer
- Use specific details from the research (tech stack, job postings, company stage, industry)
- Avoid generic statements - every sentence should reference something specific to this company
- Write as a knowledgeable peer sharing useful information, not a salesperson pitching
- NEVER use emdashes (—) in any of the emails - use commas, periods, or separate sentences instead
- Break up text into short paragraphs for easy readability

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

Remember: If your message is just a clever way to pitch your product, it's not a true PVP. Lead with genuine value."""

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
        sections = ["# Email Sequence\n"]

        for email in emails:
            sections.append(f"## Email {email['email_number']}")
            sections.append(f"**Subject:** {email['subject']}\n")
            sections.append(email['body'])
            sections.append("\n---\n")

        return "\n".join(sections)
