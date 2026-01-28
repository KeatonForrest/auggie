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

        if document.existential_data_points:
            sections.append("## Existential Data Points (Urgency Signals)")
            sections.append(document.existential_data_points)
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
        return f"""**CRITICAL: WORD LIMITS ARE MANDATORY**

Count words before submitting each email. If over the limit, rewrite shorter.

- Email 1: 75 words max
- Email 2: 100 words max
- Email 3: 60 words max

These are requirements, not guidelines.

---

You are an expert at crafting Personalized Value Propositions (PVPs) for B2B sales outreach.

**Your job:** Use research to demonstrate you understand their problem, then explain why you can help. The research is proof of understanding, not the point of the email.

Here is the research content you will be working with:

<report>
{report}
</report>

---

**CORE PRINCIPLE**

A PVP is a gift, not a pitch. You are giving them something valuable. An insight. A connection. A pattern they had not seen.

Research earns the right to explain how you help. It is not the value itself.

Bad: "I noticed X, Y, and Z about your company. Here is more about X, Y, and Z."
Good: "I noticed X. That usually leads to Y. We help companies avoid Y. Here is how one did it."

Every email should answer: "Why should they believe we can help with their specific problem?"

---

**THE PVP TEST**

Before sending, ask: "Would they thank me for this email even if they never buy?"

If no, rewrite.

---

**EMAIL STRUCTURE (PEA FRAMEWORK)**

**Email 1 - PREVIEW (The Insight)**

Job: Earn the open. Show you understand their situation. Give them something useful.

Constraints:
- 75 words max
- No product mentions
- End with a statement, not a question

Structure:
- What you observed (specific, from research)
- What that usually means for companies like them
- A useful implication or pattern

Example (68 words):
"I noticed you are hiring multiple Staff-level Golang engineers while rolling out AI agents across five use cases. That combination usually means the backend is under pressure to support workloads it was not designed for.

Most teams in this spot end up choosing between expensive vertical scaling or a long re-architecture project. There is a third path that a few companies have figured out."

---

**Email 2 - ENGAGE (The Proof)**

Job: Prove expertise. Show you have solved this before. Make them curious how.

Constraints:
- 100 words max
- One quantified outcome from a similar company
- Do NOT explain how the outcome was achieved
- No product mentions
- End with a statement that connects to them

Example (82 words):
"Fireworks AI hit the same wall. AI workloads that needed both real-time performance and flexible data handling. Their existing database forced them to choose one or build complex pipelines for both.

They fixed it in 8 weeks. Cut query latency by 60%. Stopped their backend hiring surge. AI model performance improved 3x while infrastructure costs dropped.

Your AI agents initiative has the same pattern. Five use cases, mixed workloads, and a hiring push to keep up."

---

**Email 3 - ASK (The Offer)**

Job: Make a specific, low-friction offer. Now you can mention your product.

Constraints:
- 60 words max
- Offer must be valuable even if they never buy
- Product mention is one sentence max

Example (48 words):
"Happy to do a 15-minute architecture review and show where the bottlenecks likely are. You keep the analysis either way.

MongoDB handles the mixed workload pattern your AI agents need. Worth a short conversation to see if it fits?"

---

**WRITING STYLE**

- 7th grade reading level
- No emdashes
- No parentheticals
- Short sentences. Each sentence does one job.
- 2-3 sentences per paragraph max
- Specific over clever
- Peer tone, not salesperson tone
- Never say "checking in" or "circling back"

---

**BEFORE YOU SUBMIT**

Count the words in each email body. If any email exceeds its limit, rewrite shorter.

---

Present your final output in this format:

<email_series>
<email1>
Subject: [subject line]

[body]
</email1>

<email2>
Subject: [subject line]

[body]
</email2>

<email3>
Subject: [subject line]

[body]
</email3>
</email_series>
"""

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
