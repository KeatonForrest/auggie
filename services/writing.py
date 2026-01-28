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
        return f"""You are an expert at crafting Personalized Value Propositions (PVPs) - messages so valuable that prospects would pay to receive them, even if they never buy your product.

A PVP uses publicly available data to deliver insights that directly impact the prospect's business. Unlike traditional feature-focused outreach, a PVP leads with concrete, actionable intelligence that demonstrates you understand their specific situation.

Here is the research content you will be working with:

<report>
{report}
</report>

Your goal is to create a PVP email sequence based on this research. Each email should deliver genuine, standalone value, not just a clever way to pitch a product.

---

**CORE CONCEPTS**

**The PVP Litmus Test:**
"Would they pay for this information even if they never buy from me?" If no, it is a pitch, not a PVP.

**Data Cocktail:**
Combine 2-3 public data sources to create insights no one else has. Single-source insights feel generic. Combined sources feel like real research.

Sources to combine: tech stack (BuiltWith/Stackshare), job postings, funding announcements, API response times, secondary market data, regulatory filings, app reviews, social sentiment, hiring velocity, customer reviews.

**Two-Sided Questions:**
End emails with a two-sided question that names two plausible causes for their pain. Both causes should be problems your product solves. This feels consultative, not salesy.

Formula: [Observable data point] + [Two plausible causes] + "Which is closer?"

Example: "Your /transactions endpoint is 3x slower than /accounts. That usually means either joins are compounding or you are hitting index limits. Which is closer to what you are seeing?"

---

**TYPES OF VALUE TO DELIVER**

Use the research to identify which applies:

- **Cost savings opportunity**: "We noticed X technology in your stack typically costs Y% more than Z alternative"
- **Risk mitigation**: "Your job posting mentions using [deprecated technology]. Here is the migration timeline before support ends"
- **Revenue opportunity**: "Companies with your tech stack typically see X% improvement when they address [specific gap]"
- **Competitive intelligence**: "Three of your competitors recently adopted X. Here is what they are doing differently"
- **Efficiency gains**: "Your team is hiring for X role to solve Y problem. Here is a faster approach"
- **Market timing**: "Based on your tech stack and hiring, you are likely hitting Z scaling challenge right now"

---

**EMAIL STRUCTURE (PEA FRAMEWORK)**

**Email 1 - PREVIEW** (Earn the open)
- First 120 characters must hook with specific data they will recognize as true
- Deliver one concrete insight from their public data
- End with a two-sided question, not a pitch
- Around 85 words
- Subject line should hint at the specific insight

**Email 2 - ENGAGE** (Prove expertise, create curiosity)
- Build on email 1 with social proof from similar companies
- Name the mechanism behind their problem (the "why" behind the pain)
- Include a quantified outcome but do not explain how it was achieved
- Around 100 words
- Subject line should promise concrete value

**Email 3 - ASK** (Low friction, offers value)
- Offer to do something valuable for them before they commit (audit, analysis, checklist)
- The ask itself should be a mini-PVP
- Only now mention your product, and keep it brief
- Soft call-to-action focused on continuing the conversation, not closing a sale
- Around 75 words
- Subject line should be direct

---

**WRITING STYLE**

- 7th grade reading level
- No emdashes. Use commas, periods, or separate sentences instead
- No product name until Email 3
- Each sentence does one job
- Short paragraphs, 2-3 sentences max
- Write as a knowledgeable peer sharing useful information, not a salesperson pitching
- Avoid generic statements. Every sentence should reference something specific to this company
- Never say "just checking in" or "circling back"

---

**EXAMPLES OF STRONG PVP + TWO-SIDED QUESTIONS**

Example 1 (FinTech / Database):
"You announced 3x user growth last quarter but your stack still shows PostgreSQL as primary. At that growth rate, teams usually hit either latency issues on high-volume queries or they burn engineering cycles on manual sharding. Which one is eating more time right now?"

Example 2 (Sports / CDP):
"Your secondary market data shows strong single-game demand but flat season ticket renewal. That gap usually means either your CRM cannot connect anonymous buyers to known fans, or your nurture sequences are treating first-timers and lapsed holders the same. Which is closer?"

Example 3 (SaaS / Churn):
"Your renewal rate dropped from 87% to 81% this season while performance improved. That usually means either you are missing early warning signals because engagement data is not unified, or you are seeing the signals but cannot act before the renewal window. Which is it?"

---

Present your final output in the following format:

<email_series>
<email1>
Subject: [Insert subject line]

[Insert body of first email, ending with a two-sided question]
</email1>

<email2>
Subject: [Insert subject line]

[Insert body of second email with social proof and mechanism]
</email2>

<email3>
Subject: [Insert subject line]

[Insert body of third email with low-friction ask]
</email3>
</email_series>

---

Remember: If your message is just a clever way to pitch your product, it is not a true PVP. Lead with genuine value. The prospect should thank you for these emails even if they never become a customer."""

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
