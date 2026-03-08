"""claude.py - AI research document generation using Claude API."""

import logging
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse
from openai import AsyncOpenAI
from typing import Optional
from datetime import datetime

from models import (
    ScrapedContent, ResearchDocument, TechStack, format_multi_domain_tech,
    format_tech_by_tier, InfrastructureSignals,
    JobSignals, PainInference,
)

logger = logging.getLogger(__name__)
from config import get_settings
from services.writing.types import normalize_seller_category, SELLER_RELEVANT_ROLES
from utils.icp import normalize_verticals
from utils.personas import build_target_titles

STYLE_CONTRACT = """

---

STYLE CONTRACT (applies to every section below):

**Structure rules:**
- Lead every section with a single TL;DR sentence, then use bullets for supporting detail.
- No paragraph may exceed 2 sentences. If you need more, break into bullets.

**Word limits per section:**
- PVP Seed: 60-90 words total
- Each Existential Data Point: 80-120 words
- Before Scenario: 120-180 words total across all three sub-sections
- Talking Points: max 4 bullets per sub-section (Opening Hooks, Trap-Setting Questions, Conversation Starters, Discovery Paths)
- Business Problems: one line per problem, no elaboration paragraphs

**Banned hedge phrases — do NOT use any of these:**
"it appears", "may indicate", "potentially", "it is possible that", "overall", "in summary", "in general", "it is worth noting", "it should be noted", "broadly speaking", "as mentioned above"

**Confidence qualifiers:**
- High confidence → state directly as fact
- Medium confidence → "Signals suggest [X]"
- Low confidence → "[X] is unconfirmed — inferred from [source]"

**Deduplication rule:**
State each fact exactly once in the most relevant section. Cross-reference elsewhere with "(see [Section Name])" rather than restating.

---

"""

# Section-specific word-limit annotations inserted after each ## Header
_TIGHT_WRITING_OVERRIDES = {
    "pvp seed": "(60-90 words total.)",
    "existential data points": "(80-120 words per data point.)",
    "before scenario": "(120-180 words total across all three sub-sections.)",
    "stated business problems": "(One line per problem.)",
    "business problems": "(One line per problem.)",
    "recommended talking points": "(Max 4 bullets per sub-section.)",
    "talking points": "(Max 4 bullets per sub-section.)",
}

# Phrases to strip in post-generation formatting (case-insensitive)
_HEDGE_PHRASES = [
    "it appears",
    "may indicate",
    "potentially",
    "it is possible that",
    "overall",
    "in summary",
    "in general",
    "it is worth noting",
    "it should be noted",
    "broadly speaking",
    "as mentioned above",
]

# Section dedup priority (higher index = lower priority, gets deduped)
_DEDUP_PRIORITY = [
    "existential_data_points",
    "before_scenario",
    "business_problems",
    "talking_points",
]


@dataclass
class ResearchValidationResult:
    is_valid: bool
    failed_checks: list[str] = field(default_factory=list)
    failure_details: dict[str, str] = field(default_factory=dict)


class ClaudeService:
    """Service for generating research documents using Claude."""

    def __init__(self):
        self.settings = get_settings()
        self.client = AsyncOpenAI(
            api_key=self.settings.openrouter_api_key,
            base_url="https://openrouter.ai/api/v1",
            timeout=90.0,
        )

    _SECURITY_KEYWORDS = {"security", "compliance", "soc2", "gdpr", "vulnerability", "firewall", "identity", "auth", "zero trust", "siem", "threat", "encryption", "pentest"}
    _WEB_INFRA_KEYWORDS = {"website", "monitoring", "uptime", "seo", "page speed", "web performance", "broken link", "crawl", "accessibility", "web development", "agency", "site reliability", "synthetic monitoring", "real user monitoring"}

    def _sells_security(self, problems_solved: str, product_type: str) -> bool:
        """Check if the seller's product addresses security."""
        text = problems_solved.lower()
        return any(kw in text for kw in self._SECURITY_KEYWORDS)

    def _sells_web_infrastructure(self, problems_solved: str, product_type: str) -> bool:
        """Check if the seller's product addresses website quality/monitoring."""
        text = problems_solved.lower()
        return any(kw in text for kw in self._WEB_INFRA_KEYWORDS)

    # Legacy suppression methods removed — the pipeline now handles signal filtering upstream:
    # - Security signals: hard-suppressed by pain_inference._apply_seller_weighting for non-security sellers
    # - Frontend/CDN noise: eliminated by tech_detection scoping to product domains only
    # - Website quality: not collected from marketing sites anymore

    def _build_system_prompt(self, product_context: str, retrieved_materials: str = "", seller_company: str = "",
                               target_personas: str = "", target_industries: str = "", problems_solved: str = "",
                               product_type: str = "saas", custom_signals: str = "",
                               solution_motion: str = "horizontal",
                               seller_product_category: str = "") -> str:
        """Build the system prompt defining Claude's research analyst role."""
        base_prompt = f"""Follow every section in OUTPUT FORMAT exactly. Do not skip or merge sections. Output all SCORE_ fields at the end in the exact format specified.

Your three dimension scores should rarely be within 10 points of each other. Companies almost always have uneven profiles — strong pain but weak timing, good fit but no urgency, etc. If your three scores are within 10 points, re-examine your evidence.

Your mission is to find evidence of pain. Everything else — technology, hiring, news — is context that either supports a pain hypothesis or doesn't. A research document with no pain evidence is a failed document, not a neutral one.

You produce Account Research Documents that arm salespeople with specific, verified pain signals and the insights to open conversations around them.

UNDERSTANDING THE DATA:

The company data contains several types of information with different reliability levels:

1. **VERIFIED Technology Stack** - This comes from automated scanning of the company's product subdomains (app.*, dashboard.*, portal.*, admin.*, etc.):
   - This is the REAL technology stack they use to build their product. PRIORITIZE THIS - it reveals what they actually build with.
   - **If no product subdomains were found**: This is NEUTRAL, not negative. Many companies use non-obvious subdomain patterns, SSO redirects, or single-page apps on the main domain. Do NOT editorialize about missing subdomains or call it "concerning." Simply omit the product stack section or note it was not detected.

2. **Homepage Content** - Scraped text from the main website homepage. Look for:
   - Specific projects or initiatives mentioned by name
   - Stated business problems or challenges
   - Company goals and strategic direction
   - Product positioning and business context

3. **Site Structure** - Lightweight URL pattern signals discovered from the sitemap:
   - Paths like /careers, /docs, /status, /platform, /security, /products
   - Use this as directional context about what parts of the site exist
   - Do NOT infer technology choices from path names alone

4. **Job Postings** - Strong signals about:
   - Technologies they are hiring for (these are INFERRED but reliable)
   - Specific projects or teams mentioned
   - Problems they are trying to solve
   - Technical requirements
   - How long roles have been open (longer = harder problem or higher bar)

5. **SEC EDGAR Filings** (public companies only) - From SEC.gov:
   - 8-K filings: Material events like leadership changes, M&A, restructuring, layoffs
   - Risk Factors (from 10-K): The company's own legally-required disclosure of business challenges, threats, and vulnerabilities
   - Filing dates and frequency indicate company activity and regulatory status
   - These are HIGH-CONFIDENCE signals — companies are legally obligated to report them accurately

6. **Federal Register Regulations** - Upcoming compliance deadlines from the Federal Register:
   - Final Rules with effective dates create deadline-driven urgency
   - Proposed Rules signal upcoming compliance requirements
   - Match these to the company's industry to assess regulatory pressure
   - Upcoming deadlines are strong Timing signals — companies need to act before effective dates

7. **Infrastructure Signals** - DNS, SSL, security headers, and robots.txt analysis, pre-processed into a single report:
   - Cloud provider hints from NS records, email provider from MX records
   - Certificate management practices (issuer, expiry, automation)
   - Security header grade (A-F) and robots.txt paths
   - These are factual observations — the pipeline has already scored their significance

8. **Parsed Job Signals** - Structured extraction from job posting text:
    - Technology mentions by category (language, framework, database, cloud, data, devops, security)
    - Role types and seniority distribution
    - Initiative signals (migration, platform buildout, data/AI rollout, compliance programs)
    - Delivery model and capability-gap signals inferred from hiring language
    - Roles marked as "Relevant" are most important for this seller's product category

9. **Programmatic Pain Signals** - Pre-scored inferences from combining multiple data sources:
    - Each signal has severity, confidence score, and evidence list
    - Signals are pre-weighted for seller relevance — high-confidence signals (70+) have already been validated as relevant to the seller's product
    - Synthesize into your analysis. Do NOT repeat verbatim

10. **External Context** - Web search results shaped by the seller's product category:
    - Recent news, developments, and market context
    - Technology and infrastructure mentions from external sources
    - Challenges and scaling signals from third-party coverage
    - **Hiring signals**: Role titles, tech requirements, and time-open mentions from LinkedIn/Indeed/job boards. Treat these the same as scraped job postings — they reveal what the company is investing in and struggling to fill
    - Cross-reference with first-party data for corroboration

11. **Firmographic Data** - Company size, industry, funding, contacts
"""

        if self.settings.research_tiered_prompt_enabled:
            base_prompt += """
EVIDENCE HIERARCHY:

The pipeline has already filtered and scored evidence by reliability. In the research data:
- **Product domain tech detections** are ground truth (first-party, observed).
- **Job postings and parsed signals** are high-confidence (structured, verified).
- **Pain signals** are pre-scored with confidence values — trust these scores as-is.
- **External context (Perplexity)** provides timing and market signals — cross-reference with first-party data.
- **Homepage content and site structure** are context for understanding the company, not direct evidence.

Build Existential Data Points from observed tech + job signals + high-confidence pain inferences. Use homepage content, site structure, and external context to add narrative depth.
"""

        base_prompt += f"""
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
        if seller_product_category:
            icp_parts.append(f"""- **Seller product category**: The seller builds a {seller_product_category} product. Use this to calibrate persona framing and competitor awareness, but do NOT use it to filter or score buyer accounts — that is the role of buyer company verticals below.""")
        if target_industries:
            motion = "Vertical" if solution_motion == "vertical" else "Horizontal"
            if motion == "Vertical":
                icp_parts.append(f"""- **Buyer company verticals (Vertical motion)**: The seller targets buyers in these verticals: {target_industries}. Vertical match should be weighted heavily in Fit scoring and talking points. Prospects outside the selected verticals should receive a meaningful Fit penalty. Emphasize vertical-specific pain signals such as regulatory pressure, compliance deadlines, and industry-specific technology patterns.""")
            else:
                icp_parts.append(f"""- **Buyer company verticals (Horizontal motion)**: The seller targets buyers in these verticals: {target_industries}. A vertical match is a light Fit boost only — do not hard-penalize prospects outside the selected verticals because the product can serve many industries. Avoid making strong vertical assumptions; focus on functional pain signals over industry membership.""")
        if target_personas:
            icp_parts.append(f"""- **Persona emphasis**: The seller targets these personas: {target_personas}. Focus existential data points and champion identification on those specific roles. Look for hiring and org signals relevant to those functions.""")
        if problems_solved:
            icp_parts.append(f"""- **Problem alignment**: The seller's product solves these problems: {problems_solved}. Cross-reference the prospect's observed pain against these specific problems rather than performing generic analysis.""")

        if icp_parts:
            base_prompt += "\nIDEAL CUSTOMER PROFILE:\n\n" + "\n".join(icp_parts) + "\n"

        if custom_signals:
            base_prompt += f"""
CUSTOM SIGNAL TRACKING:
The seller has asked you to pay special attention to these signals: {custom_signals}
When you find evidence of any of these in the scraped data, job postings, tech stack, or news — call them out explicitly in the relevant sections. If a custom signal appears in job titles or descriptions, highlight it in Hiring Signals. If it appears in tech stack, highlight it in Confirmed Tech Stack. Mention custom signal matches in the score evidence when relevant.
"""

        if product_type == "msp":
            base_prompt += """

PROFESSIONAL SERVICES / CONSULTANCY MODIFIER — READ BEFORE SCORING:

You are researching on behalf of a professional services firm (managed IT, data/analytics consultancy, implementation partner, or similar). This fundamentally changes how you interpret signals:

**Research Focus:**
- Look for delivery bandwidth pressure, utilization gaps, project complexity and implementation backlog, data/reporting maturity gaps, cross-functional buying friction, and compliance pressure.
- Multi-site operations, regulated industry indicators (HIPAA, PCI, SOC2, CMMC), and absence of internal specialist roles are strong signals.
- Employee count in the 20-500 range with NO dedicated specialist staff in the seller's domain is a strong signal.

**Pain Inversion:**
- Absence of specialist hiring in the seller's domain is a POSITIVE pain signal — it means the company likely lacks internal capacity and needs external services.
- Do NOT penalize for lacking technical job postings. For services prospects, zero specialist roles = maximum pain (they have no one managing the function).
- Manual processes, compliance gaps, data/reporting gaps, and operational complexity without internal specialist support are critical pain indicators.

**Fit Reframe:**
- Traditional industries with physical operations (manufacturing, distribution, dealerships, healthcare, legal, construction, logistics) are HIGH fit. Do not penalize for lacking digital transformation signals — that IS the opportunity.
- Multi-location businesses score higher — each location multiplies operational complexity.
- Companies in regulated industries (healthcare, finance, legal) that lack specialist staff face compliance risk — this is both pain and fit.
- Companies with growing data needs but no analytics team are strong fit for data/analytics consultancies.

**Timing Signals for Services:**
- Compliance deadlines (HIPAA audits, PCI recertification, cyber insurance renewals) are strong timing signals.
- Lease renewals, office moves, location expansion = infrastructure refresh moments.
- Insurance audit cycles, new regulatory requirements, and incidents in the seller's domain create urgency.
- Leadership changes at non-tech companies often trigger modernization in the seller's domain.
- Board/investor pressure for better reporting or data-driven decisions creates urgency for analytics consultancies.

"""

        base_prompt += """

---

ANALYTICAL METHODOLOGIES:

The following methodologies govern how you analyze signals and construct insights. Reference these when producing the corresponding output sections.

### Before Scenario Analysis

For every company, construct a Before Scenario — a picture of life before the seller's product.
This has three components:

1. **Problems**: What specific, observable business problems exist? Not "they might struggle with X"
   but "their job posting for Senior DB Engineer has been open 4 months and mentions migration challenges."

2. **Negative Consequences**: What happens if these problems persist? Project forward:
   - [Observable Behavior] → [Operational Impact] → [Financial/Strategic Consequence]
   - Example: "4-month open DB role → manual query optimization consuming senior eng time →
     feature velocity declining while infrastructure costs rise"

3. **Current Attempts**: How are they trying to solve it today, and why is it insufficient?
   - Look for: tools in their stack that partially address the problem, hiring for roles that
     suggest manual workarounds, blog posts about homegrown solutions
   - The gap between their current approach and a real solution IS the sales opportunity

When analyzing the prospect, also look for:
- **Pain point matches**: Does the prospect have problems that align with what your product solves?
- **Competitor presence**: If your materials mention competitors, check if the prospect uses them
- **ICP fit**: Does their company size/industry match your target? Note fit or misfit.
- **Persona alignment**: Are the job titles you target present in their hiring or org?
- **Opportunity signals**: Look for initiatives, projects, or challenges where your product could help

### Existential Data Points

An existential data point is the business equivalent of chest pain. You do not ignore it, you do not comparison shop, and you do not wait six months to address it.

METRIC + THRESHOLD + CONSEQUENCE FORMAT:

Every existential data point must follow this structure:
  [METRIC] at [THRESHOLD] → [CONSEQUENCE]

Calibrate thresholds against industry benchmarks or common sense:
- A role open 2 weeks is normal. A role open 4+ months is a signal.
- 3 analytics tools is normal. 12 analytics tools without a CDP is fragmentation.
- One cloud provider is standard. Three cloud providers across DNS, app, and CDN is complexity tax.

If you cannot express a signal as Metric+Threshold+Consequence, it is an observation, not an
existential data point. Observations go in Business Problems. Only signals that pass the Chest
Pain Test belong here.

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
- Monolithic architecture + no migration roles posted = refactor pressure

Competitive Urgency:
- Competitor funding/acquisition + feature gap = market pressure
- Lost deal mentions + competitor tech adoption = displacement risk
- Market share decline + slower release velocity = innovation gap

Organizational Pain:
- Role open 4+ months = hard problem or broken process
- High turnover signals + critical function hiring = instability
- Reorg announcements + duplicate tool purchases = integration mess

Infrastructure Gaps:
- Multiple cloud providers (DNS + tech stack) = multi-cloud complexity tax
- 6+ analytics/ad tools without a CDP = identity fragmentation and data governance pain
- Heavy data role hiring + single database tech = data infrastructure scaling pressure
- Single cloud vendor across DNS, tech stack, CDN = vendor lock-in risk
- Skewed seniority hiring (all senior or all junior) = organizational imbalance
- 40+ distinct technologies = tool sprawl and governance burden
- Tech debt + scaling pressure + hiring anomaly compounding = engineering capacity crisis
- Identity fragmentation + tag bloat + marketing mismatch compounding = marketing infrastructure debt
- Product subdomains present but no APM/monitoring detected = observability gap
- Single database + data/backend hiring + no caching layer = database scaling pressure
- Multiple auth/identity providers across subdomains = auth fragmentation and identity management pain

### Talking Points Methodology

AUDIENCE FILTER RULES — apply to all Opening Hooks and Conversation Starters:

1. **Security details are for security buyers only.** Do NOT lead with security header grades, missing DKIM/SPF/DMARC, certificate expiry, or security posture scores UNLESS the seller's product is a security product or the target persona is a security role (CISO, security engineer, etc.). These signals are valuable for the Existential Data Points section but make terrible opening hooks for non-security buyers — they come across as a vulnerability scan, not a sales conversation.

2. **Match signal to buyer's domain.** An engineering leader cares about tech debt, scaling pressure, and hiring gaps. A marketing leader cares about analytics sprawl and identity fragmentation. A CTO cares about architecture and platform decisions. Choose hooks that match what the buyer thinks about daily.

3. **No duplicate signals.** Each opening hook should surface a DIFFERENT insight. Do not use security headers in one hook and DKIM in another — those are the same signal reworded. Spread hooks across different categories (engineering, operations, business, competitive).

4. **Business impact > technical detail.** "50% staff reduction while maintaining 29M users" is a strong hook. "Missing DKIM authentication" is not — unless you are selling email security.

**Opening Hook Construction:**
List 3-5 specific, concrete facts that could open a cold email. These must be things the prospect will immediately recognize as true about their business.

Good examples:
- "Your /api subdomain shows response times averaging 340ms"
- "You have had a Senior Database Engineer role open since September"
- "Your app stack shows Redis but your job posting mentions caching problems"

Do NOT include generic statements like "You are a fast-growing fintech" or "Companies like yours often struggle with X."

**Trap-Setting Questions:**
For each existential data point, craft a question where the research already tells you the answer.
The purpose is not to learn — it's to demonstrate that you understand their situation deeply enough
to ask the right question.

Format: "When [observable fact from research], most teams find [projected consequence].
How is your team handling [specific challenge]?"

The seller already knows, from the research, what the likely answer is. The question opens a
conversation the prospect wants to have because someone finally understands the problem.

Examples:
- "With your DB Engineer role open since September and 3x user growth from Series B, most teams
  find query optimization consuming senior eng cycles. How is your team handling the scaling
  pressure?" (You know from the research they have no DB tooling — the question surfaces the gap.)
- "I noticed your app stack shows Redis alongside job postings mentioning caching problems.
  Teams in that situation usually find the caching layer was built for a smaller scale.
  Is that what you're seeing?" (You know from the tech scan + job posting the answer is yes.)
"""

        if target_personas:
            base_prompt += f"""
PERSONA-AWARE DIRECTIVES (target: {target_personas}):
- **Hooks**: Frame opening hooks through the lens of what matters to {target_personas}. For example, for marketing leaders emphasize marketing tech, campaign infrastructure, and attribution signals; for legal ops emphasize compliance, contract management, and regulatory exposure; for engineering leaders emphasize tech stack, scaling, and developer productivity signals.
- **Trap-Setting Questions**: Both causes in each two-sided question should resonate with the daily concerns of {target_personas}. Frame root causes in terms these personas would naturally think about.
- **Conversation Starters**: Reference challenges specific to {target_personas}'s function, not just generic company observations. Connect observations to what these personas care about day-to-day.
"""

        if self.settings.research_tight_writing_enabled:
            base_prompt += STYLE_CONTRACT

        base_prompt += """

---

OUTPUT FORMAT:

## Company Overview
Brief summary of what the company does, stage, and market position. 2-3 sentences max.

## Specific Projects & Initiatives
Named projects, product launches, or strategic initiatives mentioned in their content. Be specific. If none found, say so.

## Confirmed Technology Stack
Separate by subdomain type, then group technologies by category within each subdomain. Use sub-bullets for categories.

For each subdomain group:
- **Product/App Stack** (app.*, dashboard.*, portal.*, api.* subdomains)
- **Marketing Stack** (www or main domain — less relevant for technical sales)
- **Inferred from Hiring** (technologies mentioned in job postings, flag as inferred)

Within each group, organize by category (e.g., Frontend, Backend/Languages, Databases, Cloud/Infrastructure, CDN/Caching, Analytics, CMS, Ecommerce, Libraries, etc.). Do NOT dump a flat comma-separated list. Example:

**Marketing Stack (example.com):**
- **CMS:** WordPress, Drupal
- **CDN/Caching:** Cloudflare, Varnish
- **Analytics:** Google Analytics, Hotjar
- **Frontend:** React, jQuery
- **Languages:** PHP

## Technical Hiring Signals
Current open roles with:
- Role title and seniority
- How long the role has been open (if available)
- Specific technologies or problems mentioned in the posting
- What this signals about their priorities or pain

## Stated Business Problems
Direct quotes or paraphrases of challenges the company has publicly acknowledged. Source each one (careers page, blog post, press release, etc.).

## Existential Data Points
For each data point found, combine multiple data sources to build the case:

**Format for each:**
- **Signal**: What you observed (be specific)
- **Sources**: What data you combined to identify this
- **Threshold**: Why it matters now (the tipping point)
- **Consequence**: What happens if ignored
- **Time Pressure**: How long before it becomes critical (if estimable)

Summary format: [SIGNAL] at [THRESHOLD] creates [CONSEQUENCE] within [TIMEFRAME]

Example: "PostgreSQL as primary database (detected on app.company.com) + 3x user growth announced (from Series B press release) + no database roles open (from careers page) = performance degradation risk within 3-6 months, and they are not actively addressing it."

If no existential signals found, state "No immediate urgency signals identified - this may be a longer sales cycle."

## Before Scenario
Using the Before Scenario methodology (see Analytical Methodologies above), synthesize the Before Scenario for this prospect:

**Problems (Observable):**
- [List specific, verified problems with sources]

**Negative Consequences (Projected):**
- [For each problem: consequence chain showing what happens if unaddressed]

**Current Attempts (Insufficient):**
- [How they're trying to solve it today and why it falls short]

If insufficient data for a full Before Scenario, state what's known and what's missing.
A partial Before Scenario is more valuable than none.

## Product Fit Analysis
Based on the research, identify:
- **Strong fit signals**: Specific evidence this prospect has problems your product solves
- **Potential objections**: Reasons they might not be ready or might resist
- **Competitor presence**: Any competing products detected in their stack
- **Champion candidates**: Roles or people who would care most about this problem

Overall fit: HIGH / MEDIUM / LOW with justification.

## Recommended Talking Points
Apply the Audience Filter Rules and construction guidelines from the Talking Points Methodology (see Analytical Methodologies above) to each sub-section below.

**Opening Hooks (use in first line of outreach):**
3-5 hooks following the Opening Hook Construction rules above.

**Trap-Setting Questions (use to end emails):**
Questions following the Trap-Setting Question format and examples above.

**Conversation Starters:**
3-5 specific talking points based on verified data. Each should reference something concrete from the research and connect to your product value.

Format: "I noticed [specific observation]. Companies in similar situations often [pattern]. How are you thinking about [related challenge]?"

**Discovery Paths:**
Provide 2-3 ranked conversation angles, ordered by strength of evidence. Each path MUST:
1. Start from a different verified signal
2. Lead to a pain point the seller's product **directly** addresses
3. Include the specific research evidence that supports the path

CRITICAL: Only include paths where the product connection is direct and obvious. 2 strong paths are better than 2 strong + 1 weak. If you cannot draw a straight line from the signal to a core product capability, drop the path. Never pad with tangential connections (e.g. DNS issues for a database product).

Format:
- **Path 1 (strongest):** [Signal] → [Pain hypothesis] → [Product connection]
  Evidence: [specific data points]
- **Path 2:** [Signal] → [Pain hypothesis] → [Product connection]
  Evidence: [specific data points]

These give the seller multiple ways into the conversation — if the first angle doesn't resonate,
they have a prepared fallback grounded in different evidence.

## Key Contacts
Relevant contacts with:
- Name and title
- Why they would care about this problem
- Any public content they have created (blog posts, podcasts, talks)

If no contact data available, state "No contact data available."

## Recommended Contacts
Based on all research signals — existential data points, before scenario, discovery paths, and product fit — recommend 2-3 persona types who would be the best entry points for a sales conversation. For each persona:

- **Title/Role**: The specific title or function (e.g., "VP of Engineering", "Director of Data Infrastructure")
- **Why This Person**: Connect their role to a specific pain signal or discovery path from the research. Reference the evidence.
- **Recommended Angle**: The specific conversation opener or insight that would resonate with this persona based on the research
- **Confidence**: HIGH (strong evidence links this role to observed pain), MEDIUM (role likely owns the problem based on indirect signals), or LOW (inferred from industry patterns, not company-specific evidence)

Map each recommendation to a Discovery Path — the persona who owns a problem is the person to talk to about it. If the research found no meaningful pain signals, recommend based on product fit and common buyer personas for the seller's product.

## Information Gaps
What important information could not be found? What would strengthen this research? Be specific about what is missing and why it matters.

## PVP Seed
Identify the single most valuable insight from this research — something specific enough that the
prospect would find it genuinely useful even if they never buy anything.

Format:
- **The Insight**: [One specific, non-obvious observation that combines multiple data sources]
- **Why It Matters**: [The business consequence the prospect may not have connected]
- **Source Evidence**: [The 2-3 data points that support this]

The PVP Seed should make the prospect think "that's a really good point" — not "that's a generic
observation about my industry." If you cannot produce a genuinely valuable insight, say so and
explain what data would be needed.

---

QUALITY CHECKLIST:

Before submitting, verify:
- [ ] Every insight references specific, verified data (not assumptions)
- [ ] Existential data points combine multiple data sources
- [ ] Opening hooks contain only facts the prospect would recognize as true
- [ ] Two-sided questions offer two plausible causes that your product addresses
- [ ] No generic industry statements that could apply to any company
- [ ] Product fit analysis is based on evidence, not hope
- [ ] Before Scenario has all three components (Problems, Consequences, Current Attempts)
- [ ] Every Existential Data Point follows Metric+Threshold+Consequence format
- [ ] Trap-setting questions reference specific research findings (not generic)
- [ ] Discovery paths are ranked by evidence strength
- [ ] PVP Seed combines 2+ data sources into a non-obvious insight
- [ ] Consequence chains project forward, not just describe current state
- [ ] Confidence levels are honest (LOW when guessing, not inflated to MEDIUM)

---

Remember: The goal is to arm the salesperson with insights so specific that the prospect thinks "How did they know that?" not "They clearly sent this to everyone."

---

OPPORTUNITY SCORING:

After completing the research document, you MUST output a structured opportunity score at the very end.

THE SCORING PHILOSOPHY:

Your scores determine who gets contacted and in what order. A score is not an academic assessment —
it is a prioritization decision. Every point matters because it changes whether this prospect gets
a call this week or never.

Score with this weight: you are deciding how a salesperson spends their finite time.
Overscoring wastes their time on bad prospects. Underscoring buries real opportunities.

Score three dimensions (each 0-100). Be precise and use the FULL range, including very low numbers (3, 7, 12) and the middle range (42, 57, 63). NEVER default to round numbers like 20, 25, 45, or 75. Each score should feel like a specific judgment, not a bucket. Most companies should NOT score above 75.

SCORING DISCIPLINE:
- Do NOT cluster scores at round numbers. Scores like 20, 25, 45, 50, 75 suggest you are bucketing rather than scoring precisely. Use the exact number your evidence justifies — 17, 23, 38, 52, 71, etc.
- Each dimension must be scored INDEPENDENTLY. Do not give similar scores across all three dimensions. A company can have high Pain but low Fit, or strong Timing but no Pain.
- When two companies have very different profiles, their scores MUST look different. If a SaaS company and a baseball training company get similar Fit scores, something is wrong.
- Use the sub-band criteria below to determine your score. Identify which sub-band your evidence matches, then pick a number within that 5-8 point range.

**Pain Score (40% weight):**
- How many existential data points did you find?
- Are the problems ones the seller's product directly addresses?
- Is there evidence of active suffering (complaints, long-open roles, tech debt)?

IMPORTANT: You are scoring based on publicly available web data, not insider knowledge. Companies rarely publish their pain directly. Score based on what signals ARE detectable — job postings mentioning problems, tech stack gaps, scaling language on careers pages, etc. A single relevant signal from public data is meaningful and should score in the 50s, not the 30s.

GROWTH-AS-PAIN RULE: Rapid growth is itself a pain signal when the company fits the seller's ICP. Fast-growing companies that match the ICP inevitably face scaling pressure in the seller's domain — even if they haven't publicly complained about it yet. If a company shows strong growth evidence (hiring velocity, funding, revenue growth, product expansion) AND fits the seller's ICP (Fit score would be 60+), treat growth as at least one clear pain signal. This floors the Pain score at 50 minimum. The stronger the growth evidence, the higher within the 50-69 range. Do NOT leave fast-growing ICP-fit companies in the 25-49 "speculative" bucket — growth at scale reliably produces the problems the seller solves.

Calibration sub-bands (pick the sub-band that matches your evidence, then choose a precise number within it):
- 93-100: 3+ compounding signals with explicit pain language ("struggling", "migrating from", "replacing") AND long-open roles (4+ months). Active incident/complaint evidence.
- 85-92: 3+ compounding signals directly addressable by seller's product. Long-open roles (4+ months) OR visible tech debt/scaling failures, but no explicit complaint language.
- 78-84: 2 pain signals, at least one specific and directly addressable (job posting names the exact problem domain). Corroborating evidence across data sources (e.g., job posting + tech stack gap).
- 70-77: 2 pain signals with product relevance but both indirect/inferred (e.g., hiring pattern + adjacent tech in stack).
- 63-69: 1 pain signal, specific and directly addressable, with corroborating context (e.g., problem mentioned + role open 2+ months).
- 57-62: 1 pain signal, explicit but generic (e.g., job posting mentions "scaling" or "performance" without specifics).
- 50-56: 1 pain signal, inferred/indirect only. Growth-as-pain with no explicit mention. Industry-typical pain with some tech evidence.
- 38-49: Speculative pain with some supporting context — right industry, some tech overlap, but no signals in postings or content. NOTE: If the company is clearly growing fast and fits the ICP, this sub-band is wrong — apply the growth-as-pain rule and score 50+.
- 25-37: Speculative pain only — inferred purely from company type. No supporting evidence.
- 0-24: No observable pain signals. Nothing suggests they need the seller's product.

**Fit Score (35% weight):**
- Does their company size/industry match the seller's ICP?
- Are the right personas (target level + function) present?
- Is there competitor presence that creates displacement opportunity?
- Does their tech stack align with integration requirements?

Calibration sub-bands (pick the sub-band that matches your evidence, then choose a precise number within it):
- 93-100: Exact ICP match — confirmed size + confirmed industry + target personas in postings + competitor in stack + tech alignment. Confirmed firmographic data required.
- 85-92: Exact ICP match — confirmed size + right industry + target personas visible. No competitor displacement opportunity. Confirmed firmographic data required.
- 78-84: Strong overlap: right industry + reasonable size + some personas. Missing 1 dimension OR lacking confirmed firmographics. (Ceiling without confirmed data.)
- 70-77: Strong overlap: right industry but size uncertain, OR right size but adjacent industry. Tech stack alignment present.
- 60-69: Partial fit: adjacent industry, some tech overlap. Company is plausibly in ICP but not clearly.
- 45-59: Partial fit: 1 dimension matches (industry OR size OR personas) but others don't. Requires stretching ICP definition.
- 30-44: Weak fit: different industry, wrong size. Only tech stack overlap or tangential connection.
- 20-29: Weak fit: no meaningful overlap. One tangential connection at best.
- 10-19: No fit: completely different market, wrong tech ecosystem.
- 0-9: Anti-fit: actively contradicts ICP. A consumer app, a restaurant, a sports team with no data infrastructure needs.

IMPORTANT: Without confirmed firmographic data (headcount, funding, revenue from SEC EDGAR filings or other verified sources), cap Fit at 84 maximum. You may infer fit from strong indirect signals (job postings, tech stack, industry presence) up to 84. Scores above 84 require confirmed data. A networking company is not an 88 Fit just because they are "enterprise tech."

**Timing Score (25% weight):**
- Is there a funding event, reorg, or leadership change creating urgency?
- Are there roles open 3+ months suggesting unresolved problems?
- Is there a regulatory deadline or competitive threat with a timeline?
- Are they actively evaluating solutions (RFP signals, comparison content)?

IMPORTANT: Active hiring and recent product launches ARE timing signals. A company that is actively posting technical roles and shipping new features is in a building phase — that's a real window. Don't require a funding round or leadership change to score above 50.

Calibration sub-bands (pick the sub-band that matches your evidence, then choose a precise number within it):
- 93-100: 3+ concurrent urgency signals (funding + hiring spike + leadership change). Active vendor evaluation or RFP evidence.
- 85-92: 2 concurrent urgency signals (e.g., recent funding + leadership change). Evidence of active transformation program.
- 78-84: 1 major urgency signal (recent funding OR leadership change) PLUS active hiring confirming follow-through.
- 70-77: 1 major urgency signal without corroborating hiring. OR significant hiring spike alone (5+ relevant roles).
- 63-69: Active building: steady technical hiring (3-4 relevant roles) + recent product launches or platform expansion.
- 57-62: Active building: moderate hiring (1-2 relevant roles) OR recent product launches. Some evidence of investment.
- 50-56: Mild activity: some hiring present, no specific urgency trigger. Company is not dormant but not visibly accelerating.
- 38-49: Minimal: limited hiring, no recent news. Company appears stable but not actively building.
- 25-37: Low activity: no hiring in relevant areas. Last news 6+ months old.
- 0-24: Anti-timing: layoffs, budget cuts, hiring freeze, product sunsetting. OR zero timing signals found.

CONCRETE EXAMPLE (for a database product seller):
- A mid-market fintech company (confirmed 500 employees via SEC filings) hiring 3 backend engineers and 1 data engineer, with job postings open 4+ months mentioning "scaling challenges" and "migration from legacy systems," recently raised Series C, and using a competitor's product visible in their tech stack → Pain: 88 (85-92: 3+ compounding signals, long-open roles), Fit: 85 (85-92: confirmed size + industry + personas + competitor), Timing: 82 (78-84: funding + active hiring confirming follow-through), Composite: 86
- A SaaS platform (enterprise customers, right industry) hiring multiple backend engineers with postings mentioning "search infrastructure" and "recommendation systems," active product launches, but no confirmed database pain or long-open roles → Pain: 57 (57-62: 1 explicit but generic signal), Fit: 76 (70-77: right industry, size uncertain), Timing: 61 (57-62: moderate hiring + product launches), Composite: 64
- A regional bank with no technical hiring, no visible API infrastructure, no recent funding or leadership changes, and steady-state operations → Pain: 27 (25-37: speculative pain only), Fit: 48 (45-59: partial fit, 1 dimension matches), Timing: 23 (0-24: zero timing signals), Composite: 33
- A fast-growing enterprise healthcare company (strong ICP fit, data-intensive operations, recent product expansion, active hiring) but no explicit pain signals in job postings or public content → Pain: 53 (50-56: growth-as-pain, inferred), Fit: 72 (70-77: right industry, size uncertain), Timing: 57 (57-62: moderate hiring + product launches), Composite: 60. Growth-as-pain rule applies: rapid growth + ICP fit floors pain at 50+, not the 38 it would get from speculative inference alone.
- A baseball analytics company with data-intensive operations but no database pain signals, MySQL in their stack, no technical hiring, private company → Pain: 33 (25-37: speculative pain only), Fit: 41 (30-44: weak fit, tangential connection), Timing: 24 (0-24: zero timing signals), Composite: 33

Composite = (Pain × 0.4) + (Fit × 0.35) + (Timing × 0.25), rounded to nearest integer.

Output the scores in this EXACT format at the very end of your response (after all other sections):

## Opportunity Score

SCORE_PAIN: [0-100]
SCORE_PAIN_EVIDENCE: [Bullet list of specific signals that justify the pain score. Prioritize signals relevant to the seller's product. Security infrastructure gaps (headers, DKIM, certs) should only be listed if the seller's product addresses security. If none, write "No pain signals found."]
SCORE_FIT: [0-100]
SCORE_FIT_EVIDENCE: [Bullet list of specific signals that justify the fit score. If none, write "No fit signals found."]
SCORE_TIMING: [0-100]
SCORE_TIMING_EVIDENCE: [Bullet list of specific signals that justify the timing score. If none, write "No timing signals found."]
SCORE_COMPOSITE: [0-100]
SCORE_SUMMARY: [1-2 sentence justification for the composite score]
"""

        if self.settings.research_tight_writing_enabled:
            base_prompt = self._apply_tight_writing_overrides(base_prompt)

        return base_prompt

    def _apply_tight_writing_overrides(self, prompt: str) -> str:
        """Insert word-limit annotations after each ## Header in the prompt."""
        lines = prompt.split("\n")
        result = []
        for line in lines:
            result.append(line)
            if line.startswith("## "):
                header_text = line[3:].strip().lower()
                override = _TIGHT_WRITING_OVERRIDES.get(header_text)
                if override:
                    result.append(override)
        return "\n".join(result)

    @staticmethod
    def _format_infrastructure_section(
        infra: Optional[InfrastructureSignals] = None,
    ) -> list[str]:
        """Format collapsed infrastructure signals into one prompt section."""
        if not infra:
            return []

        lines: list[str] = []
        has_content = False

        if infra.ns_provider or infra.cloud_provider_hints:
            lines.append("## Infrastructure Signals")
            has_content = True
            if infra.ns_provider:
                lines.append(f"- DNS: {infra.ns_provider}")
            if infra.cloud_provider_hints:
                lines.append(f"- Cloud: {', '.join(infra.cloud_provider_hints)}")

        if infra.ssl_issuer:
            if not has_content:
                lines.append("## Infrastructure Signals")
                has_content = True
            parts = [f"Issuer: {infra.ssl_issuer}"]
            if infra.ssl_expiry_days is not None:
                parts.append(f"expires in {infra.ssl_expiry_days}d")
            if infra.ssl_automation_inferred:
                parts.append("auto-renewed")
            lines.append(f"- SSL: {', '.join(parts)}")

        if infra.security_grade:
            if not has_content:
                lines.append("## Infrastructure Signals")
                has_content = True
            lines.append(f"- Security headers: {infra.security_grade} ({infra.security_score}/6)")

        if infra.robots_api_paths or infra.robots_admin_paths:
            if not has_content:
                lines.append("## Infrastructure Signals")
                has_content = True
            if infra.robots_api_paths:
                lines.append(f"- API paths: {', '.join(infra.robots_api_paths)}")
            if infra.robots_admin_paths:
                lines.append(f"- Admin paths: {', '.join(infra.robots_admin_paths)}")

        return lines

    @staticmethod
    def _format_job_signals_section(job_signals: JobSignals, seller_product_category: str = "") -> list[str]:
        """Format parsed job signals, splitting role types by relevance when a category is known."""
        lines: list[str] = ["## Parsed Job Signals"]

        # Tech mentions by category
        by_cat: dict[str, list[str]] = {}
        for tm in job_signals.tech_mentions:
            by_cat.setdefault(tm.category, []).append(f"{tm.name} (x{tm.count})")
        for cat, items in by_cat.items():
            lines.append(f"- {cat}: {', '.join(items)}")

        # Role types — split into relevant/other when category is known
        if job_signals.role_types:
            slug = normalize_seller_category(seller_product_category)
            relevant_set = SELLER_RELEVANT_ROLES.get(slug, set()) if slug else set()

            if relevant_set:
                relevant = [r for r in job_signals.role_types if r in relevant_set]
                other = [r for r in job_signals.role_types if r not in relevant_set]
                if relevant:
                    lines.append(
                        f"- Relevant role types ({seller_product_category} seller): "
                        f"{', '.join(relevant)}"
                    )
                if other:
                    lines.append(f"- Other role types: {', '.join(other)}")
                if not relevant and not other:
                    lines.append(f"- Role types: {', '.join(job_signals.role_types)}")
            else:
                lines.append(f"- Role types: {', '.join(job_signals.role_types)}")

        if job_signals.role_type_counts:
            ordered_counts = sorted(
                job_signals.role_type_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )
            lines.append(
                "- Role counts: "
                + ", ".join(f"{role} x{count}" for role, count in ordered_counts)
            )

        # Seniority distribution
        if job_signals.seniority_distribution:
            seniority_str = ", ".join(f"{k}: {v}" for k, v in job_signals.seniority_distribution.items())
            lines.append(f"- Seniority: {seniority_str}")

        if job_signals.initiative_signals:
            lines.append(f"- Initiative signals: {', '.join(job_signals.initiative_signals)}")

        if job_signals.delivery_model_signals:
            lines.append(f"- Delivery model signals: {', '.join(job_signals.delivery_model_signals)}")

        if job_signals.capacity_signals:
            lines.append(f"- Capacity signals: {', '.join(job_signals.capacity_signals)}")

        if job_signals.capability_gap_signals:
            lines.append(f"- Capability gaps: {', '.join(job_signals.capability_gap_signals)}")

        return lines

    def _build_user_prompt(
        self,
        company_url: str,
        scraped: ScrapedContent,
        tech_by_domain: Optional[dict[str, TechStack]] = None,
        infra: Optional[InfrastructureSignals] = None,
        job_signals: Optional[JobSignals] = None,
        pain_inferences: Optional[list[PainInference]] = None,
        seller_product_category: str = "",
    ) -> str:
        """Dispatch to tiered or flat user prompt based on feature flag."""
        if self.settings.research_tiered_prompt_enabled:
            return self._build_tiered_user_prompt(
                company_url, scraped, tech_by_domain,
                infra=infra, job_signals=job_signals,
                pain_inferences=pain_inferences,
                seller_product_category=seller_product_category,
            )
        return self._build_flat_user_prompt(
            company_url, scraped, tech_by_domain,
            infra=infra, job_signals=job_signals,
            pain_inferences=pain_inferences,
            seller_product_category=seller_product_category,
        )

    def _build_flat_user_prompt(
        self,
        company_url: str,
        scraped: ScrapedContent,
        tech_by_domain: Optional[dict[str, TechStack]] = None,
        infra: Optional[InfrastructureSignals] = None,
        job_signals: Optional[JobSignals] = None,
        pain_inferences: Optional[list[PainInference]] = None,
        seller_product_category: str = "",
    ) -> str:
        """Build the user prompt with all scraped research data (flat, original format)."""
        sections = [f"# Research Data for {company_url}\n"]
        site_structure_line = self._format_site_structure(scraped.site_structure)

        if tech_by_domain:
            sections.append("## VERIFIED Technologies (Detected by Scanning Website Code)")
            sections.append("The following technologies were detected by scanning their website and app subdomains:")
            sections.append("")
            sections.append(format_multi_domain_tech(tech_by_domain))
            sections.append("")
            sections.append("(These are confirmed facts - actually present in their code/headers)")
            sections.append("")

        # Infrastructure signals (DNS + SSL + security headers + robots) — one section
        infra_lines = self._format_infrastructure_section(infra)
        if infra_lines:
            sections.extend(infra_lines)
            sections.append("")

        if job_signals and (job_signals.tech_mentions or job_signals.role_types):
            sections.extend(self._format_job_signals_section(job_signals, seller_product_category))
            sections.append("")

        if pain_inferences:
            # Separate action-tier-eligible from background-only inferences
            action_tier = [pi for pi in pain_inferences if not pi.category.startswith("_background_")]
            background_only = [pi for pi in pain_inferences if pi.category.startswith("_background_")]

            if action_tier:
                sections.append("## Programmatic Pain Signals")
                sections.append("Use these as STARTING POINTS. Validate against other data. Do not repeat verbatim.")
                sections.append("")
                # Group by category in fixed order
                category_order = ["security", "engineering", "operations", "marketing", "data"]
                category_labels = {
                    "security": "Security", "engineering": "Engineering",
                    "operations": "Operations", "marketing": "Marketing", "data": "Data",
                }
                by_cat: dict[str, list[PainInference]] = {}
                for pi in action_tier:
                    by_cat.setdefault(pi.category or "other", []).append(pi)
                for cat in category_order:
                    group = by_cat.get(cat, [])
                    if not group:
                        continue
                    group.sort(key=lambda x: x.confidence, reverse=True)
                    sections.append(f"### {category_labels.get(cat, cat.title())} ({len(group)} signal{'s' if len(group) != 1 else ''})")
                    for pi in group:
                        sections.append(f"**{pi.title}** (severity: {pi.severity}, confidence: {pi.confidence})")
                        sections.append(f"  {pi.description}")
                        for ev in pi.evidence:
                            sections.append(f"  - {ev}")
                        sections.append("")

            if background_only:
                sections.append("## Background-Only Signals (DO NOT use in Action Tier)")
                sections.append("These signals were flagged as irrelevant to the seller's product category. "
                                "Do NOT include them in Existential Data Points, PVP Seed, Talking Points, "
                                "or Before Scenario. They are provided for optional context only.")
                sections.append("")
                for pi in background_only:
                    real_cat = pi.category.removeprefix("_background_")
                    sections.append(f"**{pi.title}** [{real_cat}] (severity: {pi.severity}, confidence: {pi.confidence})")
                    sections.append(f"  {pi.description}")
                    sections.append("")

        if scraped.firmographics:
            sections.append("## CONFIRMED Firmographic Data (from connected data provider)")
            sections.append(scraped.firmographics)
            sections.append("")

        if scraped.homepage:
            sections.append("## Homepage Content")
            sections.append(scraped.homepage[:5000])
            sections.append("")

        if site_structure_line:
            sections.append("## Site Structure")
            sections.append(site_structure_line)
            sections.append("")

        if scraped.job_postings:
            sections.append("## Detailed Job Postings")
            sections.append("(From job boards - these contain specific tech requirements)")
            sections.append(scraped.job_postings[:15000])
            sections.append("")

        if scraped.edgar_filings:
            sections.append("## SEC EDGAR Filings (Public Company)")
            sections.append("(From SEC.gov - official regulatory filings. 8-K = material events, Risk Factors = company-disclosed challenges)")
            sections.append(scraped.edgar_filings[:10000])
            sections.append("")

        if scraped.federal_regulations:
            sections.append("## Upcoming Federal Regulations")
            sections.append("(From Federal Register — upcoming compliance deadlines relevant to this company's industry)")
            sections.append(scraped.federal_regulations[:6000])
            sections.append("")

        if scraped.web_mentions:
            sections.append("## Third-Party Web Mentions")
            sections.append("(From Perplexity and external web sources — recent news, market context, press coverage, and third-party references.)")
            sections.append(scraped.web_mentions[:10000])
            sections.append("")

        sections.append("---")
        sections.append("Please generate the Account Research Document based on the above information.")

        return "\n".join(sections)

    @staticmethod
    def _split_pain_by_tier(
        pain_inferences: list[PainInference],
    ) -> dict[str, list[PainInference]]:
        """Split pain inferences into tier1/tier2/tier3/background buckets."""
        buckets: dict[str, list[PainInference]] = {
            "tier1": [], "tier2": [], "tier3": [], "background": [],
        }
        for pi in pain_inferences:
            if pi.category.startswith("_background_"):
                buckets["background"].append(pi)
            elif pi.confidence >= 70:
                buckets["tier1"].append(pi)
            elif pi.confidence >= 40:
                buckets["tier2"].append(pi)
            else:
                buckets["tier3"].append(pi)
        return buckets

    @staticmethod
    def _format_pain_group(pains: list[PainInference], is_background: bool = False) -> list[str]:
        """Format a group of pain inferences, grouped by category in fixed order."""
        if not pains:
            return []

        lines: list[str] = []
        category_order = ["security", "engineering", "operations", "marketing", "data"]
        category_labels = {
            "security": "Security", "engineering": "Engineering",
            "operations": "Operations", "marketing": "Marketing", "data": "Data",
        }
        by_cat: dict[str, list[PainInference]] = {}
        for pi in pains:
            cat = pi.category.removeprefix("_background_") if is_background else (pi.category or "other")
            by_cat.setdefault(cat, []).append(pi)

        for cat in category_order:
            group = by_cat.get(cat, [])
            if not group:
                continue
            group.sort(key=lambda x: x.confidence, reverse=True)
            lines.append(f"### {category_labels.get(cat, cat.title())} ({len(group)} signal{'s' if len(group) != 1 else ''})")
            for pi in group:
                if is_background:
                    real_cat = pi.category.removeprefix("_background_")
                    lines.append(f"**{pi.title}** [{real_cat}] (severity: {pi.severity}, confidence: {pi.confidence})")
                    lines.append(f"  {pi.description}")
                else:
                    lines.append(f"**{pi.title}** (severity: {pi.severity}, confidence: {pi.confidence})")
                    lines.append(f"  {pi.description}")
                    for ev in pi.evidence:
                        lines.append(f"  - {ev}")
                lines.append("")

        # Handle uncategorized pains
        for cat, group in by_cat.items():
            if cat in category_order:
                continue
            group.sort(key=lambda x: x.confidence, reverse=True)
            lines.append(f"### {cat.title()} ({len(group)} signal{'s' if len(group) != 1 else ''})")
            for pi in group:
                if is_background:
                    real_cat = pi.category.removeprefix("_background_")
                    lines.append(f"**{pi.title}** [{real_cat}] (severity: {pi.severity}, confidence: {pi.confidence})")
                    lines.append(f"  {pi.description}")
                else:
                    lines.append(f"**{pi.title}** (severity: {pi.severity}, confidence: {pi.confidence})")
                    lines.append(f"  {pi.description}")
                    for ev in pi.evidence:
                        lines.append(f"  - {ev}")
                lines.append("")

        return lines

    def _build_tiered_user_prompt(
        self,
        company_url: str,
        scraped: ScrapedContent,
        tech_by_domain: Optional[dict[str, TechStack]] = None,
        infra: Optional[InfrastructureSignals] = None,
        job_signals: Optional[JobSignals] = None,
        pain_inferences: Optional[list[PainInference]] = None,
        seller_product_category: str = "",
    ) -> str:
        """Build the user prompt organized into signal-quality tiers."""
        sections = [f"# Research Data for {company_url}\n"]
        site_structure_line = self._format_site_structure(scraped.site_structure)

        # Split tech by tier
        tier1_tech = ""
        if tech_by_domain:
            tier1_tech, _ = format_tech_by_tier(tech_by_domain)

        # Split pain by tier
        pain_buckets = self._split_pain_by_tier(pain_inferences or [])

        # --- TIER 1: HIGH-CONFIDENCE SIGNALS ---
        tier1_parts: list[str] = []

        if tier1_tech:
            tier1_parts.append("## VERIFIED Technologies — Product/App Subdomains")
            tier1_parts.append(tier1_tech)
            tier1_parts.append("")

        if job_signals and (job_signals.tech_mentions or job_signals.role_types):
            tier1_parts.extend(self._format_job_signals_section(job_signals, seller_product_category))
            tier1_parts.append("")

        if scraped.job_postings:
            tier1_parts.append("## Detailed Job Postings")
            tier1_parts.append("(From job boards - these contain specific tech requirements)")
            tier1_parts.append(scraped.job_postings[:12000])
            tier1_parts.append("")

        if scraped.firmographics:
            tier1_parts.append("## CONFIRMED Firmographic Data (from connected data provider)")
            tier1_parts.append(scraped.firmographics)
            tier1_parts.append("")

        if scraped.edgar_filings:
            tier1_parts.append("## SEC EDGAR Filings (Public Company)")
            tier1_parts.append("(From SEC.gov - official regulatory filings. 8-K = material events, Risk Factors = company-disclosed challenges)")
            tier1_parts.append(scraped.edgar_filings[:8000])
            tier1_parts.append("")

        if pain_buckets["tier1"]:
            tier1_parts.append("## High-Confidence Pain Signals (confidence >= 70)")
            tier1_parts.append("Use these as STARTING POINTS. Validate against other data. Do not repeat verbatim.")
            tier1_parts.append("")
            tier1_parts.extend(self._format_pain_group(pain_buckets["tier1"]))

        if tier1_parts:
            sections.append("## TIER 1: HIGH-CONFIDENCE SIGNALS")
            sections.append("Treat as ground truth. Build Existential Data Points primarily from this tier.")
            sections.append("")
            sections.extend(tier1_parts)

        # --- TIER 2: MEDIUM-CONFIDENCE SIGNALS ---
        tier2_parts: list[str] = []

        if scraped.homepage:
            tier2_parts.append("## Homepage Content")
            tier2_parts.append(scraped.homepage[:5000])
            tier2_parts.append("")

        if site_structure_line:
            tier2_parts.append("## Site Structure")
            tier2_parts.append(site_structure_line)
            tier2_parts.append("")

        # Infrastructure signals — consolidated into one section
        infra_lines = self._format_infrastructure_section(infra)
        if infra_lines:
            tier2_parts.extend(infra_lines)
            tier2_parts.append("")

        if pain_buckets["tier2"]:
            tier2_parts.append("## Medium-Confidence Pain Signals (confidence 40-69)")
            tier2_parts.append("These are hypotheses — include only if corroborated by other evidence.")
            tier2_parts.append("")
            tier2_parts.extend(self._format_pain_group(pain_buckets["tier2"]))

        if scraped.federal_regulations:
            tier2_parts.append("## Upcoming Federal Regulations")
            tier2_parts.append("(From Federal Register — upcoming compliance deadlines relevant to this company's industry)")
            tier2_parts.append(scraped.federal_regulations[:6000])
            tier2_parts.append("")

        if tier2_parts:
            sections.append("## TIER 2: MEDIUM-CONFIDENCE SIGNALS")
            sections.append("First-party content and corroborative data. Use to support Tier 1 signals or surface secondary patterns.")
            sections.append("")
            sections.extend(tier2_parts)

        # --- TIER 3: LOWER-CONFIDENCE SIGNALS ---
        tier3_parts: list[str] = []

        if scraped.web_mentions:
            tier3_parts.append("## Third-Party Web Mentions")
            tier3_parts.append("(From Perplexity and external web sources — recent news, market context, press coverage, and third-party references.)")
            tier3_parts.append(scraped.web_mentions[:8000])
            tier3_parts.append("")

        if pain_buckets["tier3"]:
            tier3_parts.append("## Low-Confidence Pain Signals (confidence < 40)")
            tier3_parts.append("Low confidence — include only with strong corroboration from higher tiers.")
            tier3_parts.append("")
            tier3_parts.extend(self._format_pain_group(pain_buckets["tier3"]))

        if pain_buckets["background"]:
            tier3_parts.append("## Background-Only Signals (DO NOT use in Action Tier)")
            tier3_parts.append("These signals were flagged as irrelevant to the seller's product category. "
                               "Do NOT include them in Existential Data Points, PVP Seed, Talking Points, "
                               "or Before Scenario. They are provided for optional context only.")
            tier3_parts.append("")
            tier3_parts.extend(self._format_pain_group(pain_buckets["background"], is_background=True))

        if tier3_parts:
            sections.append("## TIER 3: LOWER-CONFIDENCE SIGNALS")
            sections.append("Inferred or secondary data. Use only to corroborate higher-tier signals, not as primary evidence.")
            sections.append("")
            sections.extend(tier3_parts)

        sections.append("---")
        sections.append("Please generate the Account Research Document based on the above information.")

        return "\n".join(sections)

    @staticmethod
    def _format_site_structure(site_structure: Optional[dict[str, str]]) -> Optional[str]:
        """Collapse sitemap discoveries into a short path-only signal line."""
        if not site_structure:
            return None

        paths: list[str] = []
        seen: set[str] = set()
        for category, url in site_structure.items():
            path = (urlparse(url).path or "").strip() or f"/{category}"
            normalized = path.rstrip("/") or "/"
            if normalized == "/":
                normalized = f"/{category}"
            if normalized in seen:
                continue
            seen.add(normalized)
            paths.append(normalized)

        if not paths:
            return None
        return f"Site structure: {', '.join(paths)}"

    # --- Post-generation validation checks ---

    _GENERIC_FILLER_PHRASES = [
        "companies like yours",
        "organizations in this space",
        "businesses of this size",
        "organizations like yours",
        "businesses like yours",
    ]

    @staticmethod
    def _check_edp_sources(edp_text: str) -> Optional[str]:
        """Check that EDP section has proper source attribution.

        Returns failure message or None if pass.
        """
        if not edp_text or not edp_text.strip():
            return None
        lower = edp_text.lower()
        if "no existential" in lower or "no immediate urgency" in lower:
            return None

        has_signal_markers = "**signal**:" in lower
        has_sources_markers = "**sources**:" in lower or "sources:" in lower

        # If text is substantial with multiple bullets but zero structural markers → format not followed
        if len(edp_text) > 200 and edp_text.count("- ") >= 2 and not has_signal_markers and not has_sources_markers:
            return "EDP format not followed — no Signal/Sources markers found in substantial EDP text"

        # If proper signal markers exist, check each unit has sources
        if has_signal_markers:
            # Split into EDP units by **Signal**: markers only
            units = re.split(r"(?=\*\*Signal\*\*:)", edp_text, flags=re.IGNORECASE)
            units = [u.strip() for u in units if u.strip()]
            units_without_sources = 0
            for unit in units:
                unit_lower = unit.lower()
                if "**signal**:" in unit_lower:
                    if not re.search(r"(?:\*\*sources\*\*|sources):[ \t]*\S", unit_lower):
                        units_without_sources += 1
            if units_without_sources > 0:
                return f"{units_without_sources} EDP unit(s) missing Sources attribution"

        return None

    @staticmethod
    def _check_concrete_pain(sections: dict) -> Optional[str]:
        """Check for concrete source markers across pain-related sections.

        Returns failure message or None if pass.
        """
        source_markers = [
            "sources:", "detected on", "from careers page", "from sec filing",
            "from job posting", "open for", "open since",
        ]
        check_keys = ["existential_data_points", "business_problems", "hiring_signals", "confirmed_tech_stack"]
        combined = " ".join(sections.get(k, "") for k in check_keys).lower()
        if not combined.strip():
            return None
        if any(marker in combined for marker in source_markers):
            return None
        return "No concrete source references found in pain-related sections (EDP, Business Problems, Hiring Signals, Tech Stack)"

    @staticmethod
    def _check_score_calibration(scores: dict) -> Optional[str]:
        """Check that scores aren't lazily identical or clustered.

        Returns failure message or None if pass.
        """
        pain = scores.get("pain")
        fit = scores.get("fit")
        timing = scores.get("timing")

        # Need at least 3 scores to check
        vals = [v for v in [pain, fit, timing] if v is not None]
        if len(vals) < 3:
            return None

        # Fail if all three identical
        if pain == fit == timing:
            return f"All three scores identical ({pain}) — likely lazy output"

        # Fail if all within 8 points AND all in 55-75 lazy middle band
        spread = max(vals) - min(vals)
        if spread <= 8 and all(55 <= v <= 75 for v in vals):
            return f"All scores within {spread} points in lazy-middle band (55-75): Pain={pain}, Fit={fit}, Timing={timing}"

        # Check evidence emptiness
        for key in ["pain_evidence", "fit_evidence", "timing_evidence"]:
            val = scores.get(key)
            if val is None or (isinstance(val, str) and val.strip() == ""):
                return f"Empty evidence field: {key}"

        return None

    def _check_generic_filler(self, edp_text: str, bp_text: str) -> Optional[str]:
        """Check for generic filler phrases.

        Returns failure message or None if pass.
        """
        combined = (edp_text + " " + bp_text).lower()
        found = [p for p in self._GENERIC_FILLER_PHRASES if p in combined]
        if found:
            return f"Generic filler detected: {', '.join(repr(p) for p in found)}"
        return None

    def _validate_research(self, sections: dict, scores: dict) -> ResearchValidationResult:
        """Run all validation checks and return result."""
        failed_checks: list[str] = []
        failure_details: dict[str, str] = {}

        edp_text = sections.get("existential_data_points", "")
        bp_text = sections.get("business_problems", "")

        checks = [
            ("edp_sources", self._check_edp_sources(edp_text)),
            ("concrete_pain", self._check_concrete_pain(sections)),
            ("score_calibration", self._check_score_calibration(scores)),
            ("generic_filler", self._check_generic_filler(edp_text, bp_text)),
        ]

        for name, result in checks:
            if result is not None:
                failed_checks.append(name)
                failure_details[name] = result

        return ResearchValidationResult(
            is_valid=len(failed_checks) == 0,
            failed_checks=failed_checks,
            failure_details=failure_details,
        )

    @staticmethod
    def _build_repair_instructions(validation: ResearchValidationResult) -> str:
        """Build repair instructions from validation failures."""
        lines = ["The following quality checks failed on your output:\n"]
        for check_name in validation.failed_checks:
            detail = validation.failure_details.get(check_name, "")
            lines.append(f"- **{check_name}**: {detail}")

        lines.append("")
        lines.append("Fix instructions:")
        if "edp_sources" in validation.failed_checks:
            lines.append("- Each Existential Data Point must use the **Signal**/**Sources**/**Threshold**/**Consequence** format. Add **Sources**: lines citing where each claim came from.")
        if "concrete_pain" in validation.failed_checks:
            lines.append("- Add concrete source references (e.g., 'Detected on app.example.com', 'From job posting', 'From SEC filing') to pain-related sections.")
        if "score_calibration" in validation.failed_checks:
            lines.append("- Re-score each dimension independently. Companies almost always have uneven profiles. Ensure each score reflects distinct evidence and provide non-empty evidence fields.")
        if "generic_filler" in validation.failed_checks:
            lines.append("- Remove generic filler phrases. Replace with specific, company-level observations from the research data.")

        lines.append("")
        lines.append("Fix ONLY the failing sections + Opportunity Score.")
        lines.append("Do not invent sources. Cite where each claim came from.")
        lines.append("Do not remove sections; if missing evidence, add 'No X signals found' with a brief reason.")
        lines.append("Keep claims tied to the provided research data; if unsure, move to Information Gaps.")
        lines.append("Preserve all sections that passed.")

        return "\n".join(lines)

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
        product_type: str = "saas",
        infra: Optional[InfrastructureSignals] = None,
        job_signals: Optional[JobSignals] = None,
        pain_inferences: Optional[list[PainInference]] = None,
        custom_signals: str = "",
        solution_motion: str = "horizontal",
        seller_product_category: str = "",
    ) -> ResearchDocument:
        """Generate the full Account Research Document using Claude."""
        normalized_industries = ""
        if target_industries and target_industries.strip():
            raw_industries = [i.strip() for i in target_industries.split(",") if i.strip()]
            normalized_industries = ", ".join(normalize_verticals(raw_industries))

        normalized_personas = ""
        if target_personas and target_personas.strip():
            normalized_personas = ", ".join(build_target_titles(target_personas, max_titles=5))

        system_prompt = self._build_system_prompt(
            product_context, retrieved_materials, seller_company,
            target_personas=normalized_personas or target_personas,
            target_industries=normalized_industries or target_industries,
            problems_solved=problems_solved, product_type=product_type,
            custom_signals=custom_signals, solution_motion=solution_motion,
            seller_product_category=seller_product_category,
        )
        user_prompt = self._build_user_prompt(
            company_url, scraped, tech_by_domain,
            infra=infra, job_signals=job_signals,
            pain_inferences=pain_inferences,
            seller_product_category=seller_product_category,
        )

        model = self.settings.research_model
        try:
            response = await self.client.chat.completions.create(
                model=model,
                max_tokens=16000,
                temperature=1.0,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
        except Exception as exc:
            logger.exception(
                "Research generation call failed",
                extra={"event_type": "research_generation_failed", "company_url": str(company_url), "model": model},
            )
            raise RuntimeError("Research generation failed. Please try again.") from exc

        choices = getattr(response, "choices", None) or []
        if not choices or not getattr(choices[0], "message", None):
            logger.warning(
                "Research generation returned no choices",
                extra={"event_type": "research_generation_no_choices", "company_url": str(company_url), "model": model},
            )
            raise RuntimeError("Research generation failed. Please try again.")

        full_markdown = getattr(choices[0].message, "content", "") or ""
        thinking_content = ""
        sections = self._parse_sections(full_markdown)
        scores = self._parse_scores(full_markdown)

        # --- Validation + Repair (gated by feature flag) ---
        if self.settings.research_validation_enabled:
            validation = self._validate_research(sections, scores)
            if not validation.is_valid:
                logger.warning(
                    "Research validation failed",
                    extra={
                        "company_url": str(company_url),
                        "failed_checks": validation.failed_checks,
                        "model": model,
                    },
                )
                try:
                    repair_instructions = self._build_repair_instructions(validation)
                    repair_response = await self.client.chat.completions.create(
                        model=model,
                        max_tokens=16000,
                        temperature=1.0,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                            {"role": "assistant", "content": full_markdown},
                            {"role": "user", "content": repair_instructions},
                        ],
                    )
                    repair_choices = getattr(repair_response, "choices", None) or []
                    if not repair_choices or not getattr(repair_choices[0], "message", None):
                        raise RuntimeError("Research repair returned no choices")
                    repaired_markdown = getattr(repair_choices[0].message, "content", "") or ""
                    repaired_sections = self._parse_sections(repaired_markdown)
                    repaired_scores = self._parse_scores(repaired_markdown)
                    repair_validation = self._validate_research(repaired_sections, repaired_scores)

                    if repair_validation.is_valid:
                        full_markdown = repaired_markdown
                        sections = repaired_sections
                        scores = repaired_scores
                        logger.info("Research repair succeeded", extra={"company_url": str(company_url)})
                    else:
                        # Fail-open: keep original
                        logger.warning(
                            "Research repair still failed, keeping original",
                            extra={
                                "company_url": str(company_url),
                                "failed_checks": repair_validation.failed_checks,
                            },
                        )
                except Exception:
                    # Fail-open: keep original on any error
                    logger.exception("Research repair call failed, keeping original", extra={"company_url": str(company_url)})

        if self.settings.research_tight_writing_enabled:
            sections = self._format_sections(sections)

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
            before_scenario=sections.get("before_scenario", ""),
            pvp_seed=sections.get("pvp_seed", ""),
            required_capabilities=sections.get("required_capabilities", ""),
            product_fit=sections.get("product_fit", ""),
            talking_points=sections.get("talking_points", ""),
            recent_news="",
            key_contacts=sections.get("key_contacts", ""),
            recommended_contacts=sections.get("recommended_contacts", ""),
            information_gaps=sections.get("information_gaps", ""),
            opportunity_score=scores.get("composite"),
            pain_score=scores.get("pain"),
            fit_score=scores.get("fit"),
            timing_score=scores.get("timing"),
            score_summary=scores.get("summary"),
            pain_evidence=scores.get("pain_evidence"),
            fit_evidence=scores.get("fit_evidence"),
            timing_evidence=scores.get("timing_evidence"),
            thinking_content=thinking_content.strip() or None,
            model_used=model,
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
            "key contacts": "key_contacts",
            "contacts": "key_contacts",
            "recommended contacts": "recommended_contacts",
            "information gaps": "information_gaps",
            "before scenario": "before_scenario",
            "pvp seed": "pvp_seed",
            "required capabilities": "required_capabilities",
            "required capabilities (seller: validate before using)": "required_capabilities",
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

    def _format_sections(self, sections: dict) -> dict:
        """Post-generation formatter: strip hedges, normalize bullets, dedup.

        Fail-open: returns original sections unchanged on any error.
        """
        try:
            formatted = {}
            for key, value in sections.items():
                text = self._strip_hedge_phrases(value)
                text = self._normalize_bullets(text)
                formatted[key] = text
            formatted = self._deduplicate_across_sections(formatted)
            return formatted
        except Exception:
            return sections

    def _strip_hedge_phrases(self, text: str) -> str:
        """Remove banned hedge phrases only when they lead a sentence.

        This avoids corrupting words that merely contain a banned token
        (e.g., "Overallocation") and avoids deleting uncertainty cues in
        the middle of a sentence.
        """
        for phrase in _HEDGE_PHRASES:
            escaped = re.escape(phrase)

            # Strip phrase only when it appears at sentence/line start.
            # Examples removed:
            # - "It appears the company..."
            # - "Overall, the company..."
            # - ". In summary, the key issue..."
            sentence_start = re.compile(
                rf"(?im)(^|[.!?]\s+)\s*(?<!\w){escaped}(?!\w)\s*,?\s*"
            )
            text = sentence_start.sub(r"\1", text)

        # Normalize whitespace and remove empty bullet artifacts.
        text = re.sub(r"[ \t]{2,}", " ", text)
        text = re.sub(r"^\s*-\s*$", "", text, flags=re.MULTILINE)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _normalize_bullets(self, text: str) -> str:
        """Convert *, bullet, and dash variants to consistent '- ' style."""
        # Match lines starting with *, •, or – followed by space
        text = re.sub(r"^(\s*)[*•–]\s+", r"\1- ", text, flags=re.MULTILINE)
        return text

    def _deduplicate_across_sections(self, sections: dict) -> dict:
        """Remove exact-duplicate lines across sections, keeping highest-priority copy.

        Priority order: existential_data_points > before_scenario > business_problems > talking_points.
        Lines shorter than 20 chars are skipped (headers, labels, etc.).
        """
        seen: set[str] = set()
        result = dict(sections)

        for section_key in _DEDUP_PRIORITY:
            content = result.get(section_key, "")
            if not content:
                continue
            lines = content.split("\n")
            kept = []
            for line in lines:
                normalized = line.strip().lower()
                if len(normalized) < 20:
                    kept.append(line)
                    continue
                if normalized in seen:
                    continue
                seen.add(normalized)
                kept.append(line)
            result[section_key] = "\n".join(kept).strip()

        return result

    def _extract_domain(self, url: str) -> str:
        """Extract domain name from URL."""
        domain = url.replace("https://", "").replace("http://", "")
        domain = domain.split("/")[0]
        return domain.replace("www.", "")
