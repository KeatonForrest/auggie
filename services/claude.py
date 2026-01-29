"""claude.py - AI research document generation using Claude API."""

import re
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

    def _build_system_prompt(self, product_context: str, retrieved_materials: str = "", seller_company: str = "",
                               target_personas: str = "", target_industries: str = "", problems_solved: str = "") -> str:
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

5. **SEC EDGAR Filings** (public companies only) - From SEC.gov:
   - 8-K filings: Material events like leadership changes, M&A, restructuring, layoffs
   - Risk Factors (from 10-K): The company's own legally-required disclosure of business challenges, threats, and vulnerabilities
   - Filing dates and frequency indicate company activity and regulatory status
   - These are HIGH-CONFIDENCE signals — companies are legally obligated to report them accurately

6. **G2/Capterra Reviews** - Third-party review data about the company's products:
   - Star ratings and review volume indicate market presence and customer satisfaction
   - Negative review themes reveal pain points (scaling issues, poor support, missing features)
   - Competitor comparisons and "switching from/to" signals reveal competitive pressure
   - Low ratings in specific categories suggest areas where they need help

7. **Federal Register Regulations** - Upcoming compliance deadlines from the Federal Register:
   - Final Rules with effective dates create deadline-driven urgency
   - Proposed Rules signal upcoming compliance requirements
   - Match these to the company's industry to assess regulatory pressure
   - Upcoming deadlines are strong Timing signals — companies need to act before effective dates

8. **Firmographic Data** - Company size, industry, funding, contacts

YOUR COMPANY: {seller_company}

YOUR PRODUCT CONTEXT (the product you are selling):

{product_context}
"""

        # Add background knowledge constraints if seller company is provided
        if seller_company:
            base_prompt += f"""
BACKGROUND KNOWLEDGE ABOUT {seller_company.upper()}:

You may use your background knowledge about {seller_company} ONLY for:
- Identifying competitors in the prospect's tech stack (flag technologies that compete with {seller_company})
- Understanding general product positioning and problem space

Do NOT use background knowledge for:
- Specific features or capabilities (use only what is stated in product context or materials)
- Case studies or customer names (use only what is in uploaded materials)
- Metrics, pricing, or ROI claims

When you identify a competitor in their stack, note it as: "**Competitor detected:** [technology] - competes with {seller_company}"
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

        # Add ICP section if any ICP fields are populated
        icp_parts = []
        if target_industries:
            icp_parts.append(f"""- **Industry emphasis**: The seller targets these industries: {target_industries}. Emphasize industry-specific signals such as regulatory pressure, compliance deadlines, and industry-specific technology patterns. Score Fit higher when the prospect matches a target industry.""")
        if target_personas:
            icp_parts.append(f"""- **Persona emphasis**: The seller targets these personas: {target_personas}. Focus existential data points and champion identification on those specific roles. Look for hiring and org signals relevant to those functions.""")
        if problems_solved:
            icp_parts.append(f"""- **Problem alignment**: The seller's product solves these problems: {problems_solved}. Cross-reference the prospect's observed pain against these specific problems rather than performing generic analysis.""")

        if icp_parts:
            base_prompt += "\nIDEAL CUSTOMER PROFILE:\n\n" + "\n".join(icp_parts) + "\n"

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
"""

        if target_personas:
            base_prompt += f"""
PERSONA-AWARE HOOKS: The seller targets {target_personas}. Frame opening hooks through the lens of what matters to those personas. For example, for marketing leaders emphasize marketing tech, campaign infrastructure, and attribution signals; for legal ops emphasize compliance, contract management, and regulatory exposure; for engineering leaders emphasize tech stack, scaling, and developer productivity signals.
"""

        base_prompt += """
**Two-Sided Questions (use to end emails):**
For each existential data point, provide a two-sided question that names two plausible root causes.

Format: "[Observable signal]" usually means either [Cause A] or [Cause B]. Which is closer?

**Important**: Both causes must be problems your product could address. If only one cause relates to your product, reframe the question until both paths lead to a relevant conversation.

Examples:
- "4 open backend roles for 3+ months usually means either the scaling problems are complex enough that candidates are hesitant, or you are solving it with tooling instead. Which is closer?"
- "3x user growth on PostgreSQL usually means either you are already seeing latency issues, or you are burning engineering cycles on manual optimization. Which is it?"
"""

        if target_personas:
            base_prompt += f"""
PERSONA-AWARE QUESTIONS: Both causes in each two-sided question should resonate with the daily concerns of {target_personas}. Frame root causes in terms these personas would naturally think about.
"""

        base_prompt += """
**Conversation Starters:**
3-5 specific talking points based on verified data. Each should reference something concrete from the research and connect to your product value.

Format: "I noticed [specific observation]. Companies in similar situations often [pattern]. How are you thinking about [related challenge]?"
"""

        if target_personas:
            base_prompt += f"""
PERSONA-AWARE STARTERS: Reference challenges specific to {target_personas}'s function, not just generic company observations. Connect observations to what these personas care about day-to-day.
"""

        base_prompt += """

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

---

OPPORTUNITY SCORING:

After completing the research document, you MUST output a structured opportunity score at the very end.

Score three dimensions (each 0-100). Be precise and use the FULL range, including very low numbers (3, 7, 12) and the middle range (42, 57, 63). NEVER default to round numbers like 20, 25, 45, or 75. Each score should feel like a specific judgment, not a bucket. Most companies should NOT score above 70.

SCORING DISCIPLINE:
- Do NOT cluster scores at round numbers. Scores like 20, 25, 45, 50, 75 suggest you are bucketing rather than scoring precisely. Use the exact number your evidence justifies — 17, 23, 38, 52, 71, etc.
- Each dimension must be scored INDEPENDENTLY. Do not give similar scores across all three dimensions. A company can have high Pain but low Fit, or strong Timing but no Pain.
- When two companies have very different profiles, their scores MUST look different. If a SaaS company and a baseball training company get similar Fit scores, something is wrong.

**Pain Score (40% weight):**
- How many existential data points did you find?
- Are the problems ones the seller's product directly addresses?
- Is there evidence of active suffering (complaints, long-open roles, tech debt)?

Calibration anchors:
- 85-100: 3+ compounding pain signals directly addressable by seller's product. Long-open roles (4+ months) in relevant functions. Visible tech debt or scaling failures. Active complaints or incident signals. RARE — most companies do not score here.
- 65-84: 2+ clear pain signals with direct product relevance. Some open roles suggesting unresolved problems. Evidence of struggling with a problem the seller addresses.
- 35-64: 1 pain signal or indirect signals only. Problems exist but aren't urgent or clearly addressable. Open roles but not long-tenured.
- 10-34: Weak or speculative pain signals. No direct evidence of suffering. Inferred problems only.
- 0-9: No observable pain signals whatsoever. No relevant hiring, no tech debt indicators, no complaints. Company shows no signs of needing the seller's product.

**Fit Score (35% weight):**
- Does their company size/industry match the seller's ICP?
- Are the right personas (target level + function) present?
- Is there competitor presence that creates displacement opportunity?
- Does their tech stack align with integration requirements?

Calibration anchors:
- 85-100: Exact ICP match — right industry, right company size, target personas confirmed in job postings, tech stack aligns perfectly. Competitor presence creates clear displacement opportunity. REQUIRES confirmed firmographic data to score here.
- 65-84: Strong ICP overlap — most dimensions match. Right industry, reasonable size, some target personas visible.
- 35-64: Partial fit — adjacent industry or size is outside sweet spot. Some tech stack overlap but not core. Few or no target personas visible.
- 10-34: Weak fit — different industry, wrong size, no persona signals. Would require significant stretching of ICP definition.
- 0-9: No fit — completely outside ICP. Different market, wrong tech ecosystem, no relevant personas. A consumer app, a restaurant, a sports team with no data infrastructure needs.

IMPORTANT: Without confirmed firmographic data (headcount, funding, revenue from SEC EDGAR filings or other verified sources), do NOT assume fit. Cap Fit at 65 maximum. This cap is STRICT — do not exceed 65 without confirmed data, even if the company "seems like" a good fit. A networking company is not an 85 Fit just because they are "enterprise tech."

**Timing Score (25% weight):**
- Is there a funding event, reorg, or leadership change creating urgency?
- Are there roles open 3+ months suggesting unresolved problems?
- Is there a regulatory deadline or competitive threat with a timeline?
- Are they actively evaluating solutions (RFP signals, comparison content)?

Calibration anchors:
- 85-100: Multiple concurrent urgency signals — recent funding + hiring spike + leadership change. Active vendor evaluation. Deadline-driven need.
- 65-84: Clear urgency — recent funding OR significant hiring spike OR leadership change. Evidence of active building/transformation.
- 35-64: Moderate signals — some hiring but no spike. No recent funding or leadership changes. General growth but no urgency.
- 10-34: Weak timing — flat or declining hiring. No funding signals. No visible transformation initiatives. Stable/stagnant.
- 0-9: Anti-timing — recent layoffs, budget cuts, hiring freeze, or sunsetting product. Actively bad time to sell. OR: zero timing signals of any kind found.

IMPORTANT: Absence of signals is a STRONG negative signal for Timing. If you found ZERO timing signals — no job postings, no news, no funding, no leadership changes, no regulatory deadlines — the Timing score must be below 15, not 20. A score of 20 implies you found something weak. A score of 8 means you found nothing. Be honest about the difference.

CONCRETE EXAMPLE (for a database product seller):
- A mid-market fintech company (confirmed 500 employees via SEC filings) hiring 3 backend engineers and 1 data engineer, with job postings open 4+ months mentioning "scaling challenges" and "migration from legacy systems," recently raised Series C, and using a competitor's product visible in their tech stack → Pain: 82, Fit: 78, Timing: 76, Composite: 79
- A regional bank with no technical hiring, no visible API infrastructure, no recent funding or leadership changes, and steady-state operations → Pain: 12, Fit: 38, Timing: 8, Composite: 19
- A baseball analytics company with data-intensive operations but no database pain signals, MySQL in their stack, no technical hiring, private company → Pain: 18, Fit: 31, Timing: 11, Composite: 20

Composite = (Pain × 0.4) + (Fit × 0.35) + (Timing × 0.25), rounded to nearest integer.

Output the scores in this EXACT format at the very end of your response (after all other sections):

## Opportunity Score

SCORE_PAIN: [0-100]
SCORE_PAIN_EVIDENCE: [Bullet list of specific signals that justify the pain score. If none, write "No pain signals found."]
SCORE_FIT: [0-100]
SCORE_FIT_EVIDENCE: [Bullet list of specific signals that justify the fit score. If none, write "No fit signals found."]
SCORE_TIMING: [0-100]
SCORE_TIMING_EVIDENCE: [Bullet list of specific signals that justify the timing score. If none, write "No timing signals found."]
SCORE_COMPOSITE: [0-100]
SCORE_SUMMARY: [1-2 sentence justification for the composite score]
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

        if scraped.edgar_filings:
            sections.append("## SEC EDGAR Filings (Public Company)")
            sections.append("(From SEC.gov - official regulatory filings. 8-K = material events, Risk Factors = company-disclosed challenges)")
            sections.append(scraped.edgar_filings[:10000])
            sections.append("")

        if scraped.reviews:
            sections.append("## G2/Capterra Reviews")
            sections.append("(Third-party review data — ratings, pros/cons, competitor comparisons)")
            sections.append(scraped.reviews[:8000])
            sections.append("")

        if scraped.federal_regulations:
            sections.append("## Upcoming Federal Regulations")
            sections.append("(From Federal Register — upcoming compliance deadlines relevant to this company's industry)")
            sections.append(scraped.federal_regulations[:6000])
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
        seller_company: str = "",
        target_personas: str = "",
        target_industries: str = "",
        problems_solved: str = "",
    ) -> ResearchDocument:
        """Generate the full Account Research Document using Claude."""
        system_prompt = self._build_system_prompt(
            product_context, retrieved_materials, seller_company,
            target_personas=target_personas, target_industries=target_industries,
            problems_solved=problems_solved,
        )
        user_prompt = self._build_user_prompt(company_url, scraped, tech_by_domain)

        message = self.client.messages.create(
            model="claude-opus-4-20250514",
            max_tokens=4000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}]
        )

        full_markdown = message.content[0].text
        sections = self._parse_sections(full_markdown)
        scores = self._parse_scores(full_markdown)

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
            opportunity_score=scores.get("composite"),
            pain_score=scores.get("pain"),
            fit_score=scores.get("fit"),
            timing_score=scores.get("timing"),
            score_summary=scores.get("summary"),
            pain_evidence=scores.get("pain_evidence"),
            fit_evidence=scores.get("fit_evidence"),
            timing_evidence=scores.get("timing_evidence"),
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

    def _parse_scores(self, markdown: str) -> dict:
        """Extract structured opportunity scores from the end of Claude's output."""
        scores = {}
        patterns = {
            "pain": r"SCORE_PAIN:\s*(\d+)",
            "fit": r"SCORE_FIT:\s*(\d+)",
            "timing": r"SCORE_TIMING:\s*(\d+)",
            "composite": r"SCORE_COMPOSITE:\s*(\d+)",
        }
        for key, pattern in patterns.items():
            match = re.search(pattern, markdown)
            if match:
                val = int(match.group(1))
                scores[key] = max(0, min(100, val))

        summary_match = re.search(r"SCORE_SUMMARY:\s*(.+?)(?:\n|$)", markdown)
        if summary_match:
            scores["summary"] = summary_match.group(1).strip()

        # Extract evidence fields (multi-line: capture until next SCORE_ line or end)
        evidence_patterns = {
            "pain_evidence": r"SCORE_PAIN_EVIDENCE:\s*(.*?)(?=\nSCORE_FIT:|$)",
            "fit_evidence": r"SCORE_FIT_EVIDENCE:\s*(.*?)(?=\nSCORE_TIMING:|$)",
            "timing_evidence": r"SCORE_TIMING_EVIDENCE:\s*(.*?)(?=\nSCORE_COMPOSITE:|$)",
        }
        for key, pattern in evidence_patterns.items():
            match = re.search(pattern, markdown, re.DOTALL)
            if match:
                scores[key] = match.group(1).strip()

        # If we got individual scores but no composite, calculate it
        if "pain" in scores and "fit" in scores and "timing" in scores and "composite" not in scores:
            scores["composite"] = round(
                scores["pain"] * 0.4 + scores["fit"] * 0.35 + scores["timing"] * 0.25
            )

        return scores

    def _extract_domain(self, url: str) -> str:
        """Extract domain name from URL."""
        domain = url.replace("https://", "").replace("http://", "")
        domain = domain.split("/")[0]
        return domain.replace("www.", "")
