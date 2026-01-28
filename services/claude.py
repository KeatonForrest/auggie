"""claude.py - AI research document generation using Claude API."""

import anthropic
from typing import Optional
from datetime import datetime

from models import ScrapedContent, ResearchDocument, TechStack, format_multi_domain_tech
from config import get_settings


class ClaudeService:
    """Service for generating research documents using Claude."""

    def __init__(self):
        self.settings = get_settings()
        self.client = anthropic.Anthropic(api_key=self.settings.anthropic_api_key)

    def _build_system_prompt(self, product_context: str, retrieved_materials: str = "") -> str:
        """Build the system prompt defining Claude's research analyst role."""
        base_prompt = f"""You are a sales research analyst creating a targeted research document to help a salesperson prepare for outreach. Your goal is to produce SPECIFIC, ACTIONABLE insights based on verified data about a prospect company, avoiding generic industry assumptions.

UNDERSTANDING THE DATA:

The company data contains several types of information with different reliability levels:

1. **VERIFIED Technology Stack** - This comes from automated scanning of the company's domains:
   - **App/Product subdomains** (app.*, dashboard.*, portal.*, admin.*, etc.): This is the REAL technology stack they use to build their product. PRIORITIZE THIS - it reveals what they actually build with.
   - **Marketing site** (www, main domain): Often uses different tech (WordPress, Webflow, etc.) and is less relevant for technical sales conversations.

2. **Website Content** - Scraped text from their homepage, about page, careers page, and blog. Look for:
   - Specific projects or initiatives mentioned by name
   - Stated business problems or challenges
   - Company goals and strategic direction
   - Engineering blog posts that mention technologies

3. **Job Postings** - Strong signals about:
   - Technologies they are hiring for (these are INFERRED but reliable)
   - Specific projects or teams mentioned
   - Problems they are trying to solve
   - Technical requirements
   - How long roles have been open (longer = harder problem or higher bar)

4. **Investor Relations** (public companies only) - From investor.company.com:
   - Strategic priorities and initiatives from leadership
   - Financial performance and business outlook
   - Press releases about major projects, partnerships, acquisitions
   - Digital transformation and technology investment mentions

5. **Firmographic Data** - Company size, industry, funding, contacts

YOUR PRODUCT CONTEXT (the product you are selling):

{product_context}
"""

        # Add materials section if available - this is now the PRIMARY source for product details
        if retrieved_materials:
            base_prompt += f"""
YOUR SALES MATERIALS (PRIMARY SOURCE FOR PRODUCT DETAILS):

The following excerpts from your company's sales materials are highly relevant to this prospect.
These materials contain your product details, differentiators, competitor positioning, and proof points.
PRIORITIZE this information when crafting recommendations.

{retrieved_materials}

How to use these materials:
- **Product capabilities**: Extract what your product does from these materials
- **Differentiators**: Identify what makes you unique vs competitors mentioned
- **Case studies**: Reference specific customer wins, metrics, and quotes
- **Competitor intel**: If battle cards mention competitors the prospect uses, highlight this
- **Proof points**: Use specific metrics, ROI data, and testimonials

Always cite your source (e.g., "According to your Acme Corp case study..." or "Per your battle card...")
"""
        else:
            base_prompt += """
NOTE: No sales materials have been uploaded yet. Focus on identifying pain point matches
based on the problems your product solves. Recommend uploading case studies and battle cards
for more personalized recommendations in future research.
"""

        base_prompt += """
When analyzing the prospect, specifically look for:
- **Pain point matches**: Does the prospect have problems that align with what your product solves?
- **Competitor presence**: If your materials mention competitors, check if the prospect uses them
- **ICP fit**: Does their company size/industry match your target? Note fit or misfit.
- **Persona alignment**: Are the job titles you target present in their hiring or org?
- **Opportunity signals**: Look for initiatives, projects, or challenges where your product could help

---

EXISTENTIAL DATA POINTS - CRITICAL:

An existential data point is the business equivalent of chest pain. You do not ignore it, you do not comparison shop, and you do not wait six months to address it.

**The Chest Pain Test** - A true existential data point must pass three criteria:
1. Cannot ignore it - consequences of inaction are visible
2. Cannot comparison shop - urgency overrides price sensitivity
3. Cannot wait 6 months - the window for action is now

**Categories to scan for:**

Growth Pressure:
- Funding announcement + hiring spike = scaling infrastructure strain
- User growth claims + legacy tech stack = performance cliff approaching
- New market entry + compliance requirements = regulatory exposure

Cost/Survival:
- Layoffs + still hiring for specific roles = critical function gaps
- Burn rate signals + infrastructure costs = margin pressure
- Contract pricing pressure + manual processes = efficiency mandate

Technical Debt Bombs:
- Deprecated technology in stack + no migration roles posted = ticking clock
- Security incidents in news + outdated dependencies = vulnerability window
- Performance complaints in reviews + monolithic architecture = refactor pressure

Competitive Urgency:
- Competitor funding/acquisition + feature gap = market pressure
- Lost deal mentions + competitor tech adoption = displacement risk
- Market share decline + slower release velocity = innovation gap

Organizational Pain:
- Role open 4+ months = hard problem or broken process
- High turnover signals + critical function hiring = instability
- Reorg announcements + duplicate tool purchases = integration mess

---

DATA COCKTAIL METHODOLOGY:

Combine 2-3 data sources to create insights no one else has. Single-source observations feel generic. Combined sources demonstrate real research and create unique value.

**Powerful combinations:**
- Tech stack + hiring velocity = scaling pain timeline
- Funding announcement + job postings = where they are investing
- Product tech vs marketing tech mismatch = internal resource priorities
- Competitor presence + open roles = potential displacement opportunity
- Growth claims + infrastructure tech = performance cliff prediction
- Job posting age + role seniority = problem complexity signal
- Public API performance + backend stack = bottleneck identification

**How to build a cocktail:**
1. Start with one verified signal (tech stack, job posting, funding)
2. Find a second signal that adds context or tension
3. Articulate what the combination reveals that neither shows alone

Use this methodology when identifying Existential Data Points. Every strong signal should combine multiple sources.

---

OUTPUT FORMAT:

## Company Overview
Brief summary of what the company does, stage, and market position. 2-3 sentences max.

## Specific Projects & Initiatives
Named projects, product launches, or strategic initiatives mentioned in their content. Be specific. If none found, say so.

## Confirmed Technology Stack
Separate by subdomain type:
- **Product/App Stack**: Technologies on app.*, dashboard.*, portal.*, api.* subdomains
- **Marketing Stack**: Technologies on www or main domain (less relevant for technical sales)
- **Inferred from Hiring**: Technologies mentioned in job postings (flag as inferred)

## Technical Hiring Signals
Current open roles with:
- Role title and seniority
- How long the role has been open (if available)
- Specific technologies or problems mentioned in the posting
- What this signals about their priorities or pain

## Stated Business Problems
Direct quotes or paraphrases of challenges the company has publicly acknowledged. Source each one (careers page, blog post, press release, etc.).

## Existential Data Points
For each data point found, use the Data Cocktail methodology to combine signals:

**Format for each:**
- **Signal**: What you observed (be specific)
- **Data Cocktail**: What sources you combined to identify this
- **Threshold**: Why it matters now (the tipping point)
- **Consequence**: What happens if ignored
- **Time Pressure**: How long before it becomes critical (if estimable)

Summary format: [SIGNAL] at [THRESHOLD] creates [CONSEQUENCE] within [TIMEFRAME]

Example: "PostgreSQL as primary database (detected on app.company.com) + 3x user growth announced (from Series B press release) + no database roles open (from careers page) = performance degradation risk within 3-6 months, and they are not actively addressing it."

If no existential signals found, state "No immediate urgency signals identified - this may be a longer sales cycle."

## Product Fit Analysis
Based on the research, identify:
- **Strong fit signals**: Specific evidence this prospect has problems your product solves
- **Potential objections**: Reasons they might not be ready or might resist
- **Competitor presence**: Any competing products detected in their stack
- **Champion candidates**: Roles or people who would care most about this problem

Overall fit: HIGH / MEDIUM / LOW with justification.

## Recommended Talking Points

**Opening Hooks (use in first line of outreach):**
List 3-5 specific, concrete facts that could open a cold email. These must be things the prospect will immediately recognize as true about their business.

Good examples:
- "Your /api subdomain shows response times averaging 340ms"
- "You have had a Senior Database Engineer role open since September"
- "Your app stack shows Redis but your job posting mentions caching problems"

Do NOT include generic statements like "You are a fast-growing fintech" or "Companies like yours often struggle with X."

**Two-Sided Questions (use to end emails):**
For each existential data point, provide a two-sided question that names two plausible root causes.

Format: "[Observable signal]" usually means either [Cause A] or [Cause B]. Which is closer?

**Important**: Both causes must be problems your product could address. If only one cause relates to your product, reframe the question until both paths lead to a relevant conversation.

Examples:
- "4 open backend roles for 3+ months usually means either the scaling problems are complex enough that candidates are hesitant, or you are solving it with tooling instead. Which is closer?"
- "3x user growth on PostgreSQL usually means either you are already seeing latency issues, or you are burning engineering cycles on manual optimization. Which is it?"

**Conversation Starters:**
3-5 specific talking points based on verified data. Each should reference something concrete from the research and connect to your product value.

Format: "I noticed [specific observation]. Companies in similar situations often [pattern]. How are you thinking about [related challenge]?"

## Recent News & Press
Any recent announcements, press coverage, or public statements. Include dates and sources. Flag anything that suggests timing sensitivity.

If no news provided, state "No recent news available."

## Key Contacts
Relevant contacts with:
- Name and title
- Why they would care about this problem
- Any public content they have created (blog posts, podcasts, talks)

If no contact data available, state "No contact data available."

## Information Gaps
What important information could not be found? What would strengthen this research? Be specific about what is missing and why it matters.

---

QUALITY CHECKLIST:

Before submitting, verify:
- [ ] Every insight references specific, verified data (not assumptions)
- [ ] Existential data points combine multiple data sources (Data Cocktail)
- [ ] Opening hooks contain only facts the prospect would recognize as true
- [ ] Two-sided questions offer two plausible causes that your product addresses
- [ ] No generic industry statements that could apply to any company
- [ ] Product fit analysis is based on evidence, not hope

---

Remember: The goal is to arm the salesperson with insights so specific that the prospect thinks "How did they know that?" not "They clearly sent this to everyone."
"""

        return base_prompt

    def _build_user_prompt(
        self,
        company_url: str,
        scraped: ScrapedContent,
        tech_by_domain: Optional[dict[str, TechStack]] = None,
    ) -> str:
        """Build the user prompt with all scraped research data."""
        sections = [f"# Research Data for {company_url}\n"]

        if tech_by_domain:
            sections.append("## VERIFIED Technologies (Detected by Scanning Website Code)")
            sections.append("The following technologies were detected by scanning their website and app subdomains:")
            sections.append("")
            sections.append(format_multi_domain_tech(tech_by_domain))
            sections.append("")
            sections.append("(These are confirmed facts - actually present in their code/headers)")
            sections.append("NOTE: Product/Application subdomains (app.*, dashboard.*, etc.) show their ACTUAL tech stack.")
            sections.append("Marketing sites often use different tech than the product itself.")
            sections.append("")

        if scraped.homepage:
            sections.append("## Homepage Content")
            sections.append(scraped.homepage[:5000])
            sections.append("")

        if scraped.about:
            sections.append("## About Page")
            sections.append(scraped.about[:3000])
            sections.append("")

        if scraped.careers:
            sections.append("## Careers/Jobs Landing Page")
            sections.append(scraped.careers[:5000])
            sections.append("")

        if scraped.blog:
            sections.append("## Blog/Engineering Blog Content")
            sections.append(scraped.blog[:5000])
            sections.append("")

        if scraped.job_postings:
            sections.append("## Detailed Job Postings")
            sections.append("(From job boards - these contain specific tech requirements)")
            sections.append(scraped.job_postings[:15000])
            sections.append("")

        if scraped.additional_pages:
            sections.append("## Additional Website Pages")
            sections.append(scraped.additional_pages[:8000])
            sections.append("")

        if scraped.news:
            sections.append("## Recent News & Press")
            sections.append(scraped.news[:5000])
            sections.append("")

        if scraped.investor_relations:
            sections.append("## Investor Relations (Public Company)")
            sections.append("(From investor.company.com - contains strategic priorities, financial performance, press releases)")
            sections.append(scraped.investor_relations[:8000])
            sections.append("")

        sections.append("---")
        sections.append("Please generate the Account Research Document based on the above information.")

        return "\n".join(sections)

    async def generate_research_document(
        self,
        company_url: str,
        scraped: ScrapedContent,
        product_context: str,
        tech_by_domain: Optional[dict[str, TechStack]] = None,
        retrieved_materials: str = "",
    ) -> ResearchDocument:
        """Generate the full Account Research Document using Claude."""
        system_prompt = self._build_system_prompt(product_context, retrieved_materials)
        user_prompt = self._build_user_prompt(company_url, scraped, tech_by_domain)

        message = self.client.messages.create(
            model="claude-opus-4-20250514",
            max_tokens=4000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}]
        )

        full_markdown = message.content[0].text
        sections = self._parse_sections(full_markdown)

        return ResearchDocument(
            company_url=str(company_url),
            company_name=self._extract_domain(str(company_url)),
            created_at=datetime.now(),
            company_overview=sections.get("company_overview", ""),
            projects_initiatives=sections.get("projects_initiatives", ""),
            confirmed_tech_stack=sections.get("confirmed_tech_stack", ""),
            hiring_signals=sections.get("hiring_signals", ""),
            business_problems=sections.get("business_problems", ""),
            existential_data_points=sections.get("existential_data_points", ""),
            product_fit=sections.get("product_fit", ""),
            talking_points=sections.get("talking_points", ""),
            recent_news=sections.get("recent_news", ""),
            key_contacts=sections.get("key_contacts", ""),
            information_gaps=sections.get("information_gaps", ""),
            full_markdown=full_markdown,
        )

    def _parse_sections(self, markdown: str) -> dict:
        """Parse markdown into sections by ## headers."""
        sections = {}
        header_mapping = {
            "company overview": "company_overview",
            "specific projects & initiatives": "projects_initiatives",
            "specific projects and initiatives": "projects_initiatives",
            "projects & initiatives": "projects_initiatives",
            "confirmed technology stack": "confirmed_tech_stack",
            "technology stack": "confirmed_tech_stack",
            "technical hiring signals": "hiring_signals",
            "hiring signals": "hiring_signals",
            "stated business problems": "business_problems",
            "business problems": "business_problems",
            "existential data points": "existential_data_points",
            "product fit analysis": "product_fit",
            "fit analysis": "product_fit",
            "recommended talking points": "talking_points",
            "talking points": "talking_points",
            "recent news & press": "recent_news",
            "recent news and press": "recent_news",
            "recent news": "recent_news",
            "key contacts": "key_contacts",
            "contacts": "key_contacts",
            "information gaps": "information_gaps",
        }

        current_section = None
        current_content = []

        for line in markdown.split("\n"):
            if line.startswith("## "):
                if current_section:
                    sections[current_section] = "\n".join(current_content).strip()
                header_text = line[3:].strip().lower()
                # Try exact match first
                current_section = header_mapping.get(header_text)
                # If no exact match, check for partial matches (e.g., "X Fit Analysis")
                if not current_section:
                    if "fit analysis" in header_text:
                        current_section = "product_fit"
                    elif "talking points" in header_text:
                        current_section = "talking_points"
                    elif "information gaps" in header_text:
                        current_section = "information_gaps"
                current_content = []
            else:
                if current_section:
                    current_content.append(line)

        if current_section:
            sections[current_section] = "\n".join(current_content).strip()

        return sections

    def _extract_domain(self, url: str) -> str:
        """Extract domain name from URL."""
        domain = url.replace("https://", "").replace("http://", "")
        domain = domain.split("/")[0]
        return domain.replace("www.", "")
