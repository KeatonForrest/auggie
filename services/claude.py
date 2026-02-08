"""claude.py - AI research document generation using Claude API."""

import re
from openai import AsyncOpenAI
from typing import Optional
from datetime import datetime

from models import (
    ScrapedContent, ResearchDocument, TechStack, format_multi_domain_tech,
    DNSProfile, SSLProfile, SecurityPosture, RobotsSignals, JobSignals, PainInference,
)
from config import get_settings


class ClaudeService:
    """Service for generating research documents using Claude."""

    def __init__(self):
        self.settings = get_settings()
        self.client = AsyncOpenAI(
            api_key=self.settings.openrouter_api_key,
            base_url="https://openrouter.ai/api/v1",
            timeout=90.0,
        )

    def _build_system_prompt(self, product_context: str, retrieved_materials: str = "", seller_company: str = "",
                               target_personas: str = "", target_industries: str = "", problems_solved: str = "",
                               product_type: str = "saas") -> str:
        """Build the system prompt defining Claude's research analyst role."""
        base_prompt = f"""Follow every section in OUTPUT FORMAT exactly. Do not skip or merge sections. Output all SCORE_ fields at the end in the exact format specified.

Your three dimension scores should rarely be within 10 points of each other. Companies almost always have uneven profiles — strong pain but weak timing, good fit but no urgency, etc. If your three scores are within 10 points, re-examine your evidence.

Your mission is to find evidence of pain. Everything else — technology, hiring, news — is context that either supports a pain hypothesis or doesn't. A research document with no pain evidence is a failed document, not a neutral one.

You produce Account Research Documents that arm salespeople with specific, verified pain signals and the insights to open conversations around them.

UNDERSTANDING THE DATA:

The company data contains several types of information with different reliability levels:

1. **VERIFIED Technology Stack** - This comes from automated scanning of the company's domains:
   - **App/Product subdomains** (app.*, dashboard.*, portal.*, admin.*, etc.): This is the REAL technology stack they use to build their product. PRIORITIZE THIS - it reveals what they actually build with.
   - **Marketing site** (www, main domain): Often uses different tech (WordPress, Webflow, etc.) and is less relevant for technical sales conversations.
   - **If no product subdomains were found**: This is NEUTRAL, not negative. Many companies use non-obvious subdomain patterns, SSO redirects, or single-page apps on the main domain. Do NOT editorialize about missing subdomains or call it "concerning." Simply omit the product stack section or note it was not detected.

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

6. **Federal Register Regulations** - Upcoming compliance deadlines from the Federal Register:
   - Final Rules with effective dates create deadline-driven urgency
   - Proposed Rules signal upcoming compliance requirements
   - Match these to the company's industry to assess regulatory pressure
   - Upcoming deadlines are strong Timing signals — companies need to act before effective dates

8. **DNS Infrastructure Signals** - From automated DNS record analysis:
   - NS provider reveals cloud infrastructure (AWS, Cloudflare, GCP, Azure)
   - MX records reveal email provider (Google Workspace, Microsoft 365)
   - SPF/DKIM/DMARC presence indicates email security maturity — missing records are a concrete pain signal
   - These are VERIFIED facts from public DNS records

9. **SSL/TLS Certificate** - From automated certificate inspection:
   - Issuer and expiry reveal certificate management practices
   - Let's Encrypt = automated renewal (good hygiene); short expiry without automation = operational risk
   - Wildcard certs and SAN count hint at infrastructure complexity

10. **Security Header Analysis** - Automated scoring of 6 key HTTP security headers:
   - Grade A-F based on presence of HSTS, CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy
   - Low grades (D/F) are concrete evidence of security underinvestment — use in Existential Data Points when combined with other signals
   - Cross-reference with DNS email auth gaps for compounding security narratives

11. **Robots.txt Signals** - Parsed from the company's robots.txt:
    - Disallowed /api or /graphql paths confirm API infrastructure exists
    - Disallowed /admin paths confirm internal tooling
    - Crawl-delay values hint at server capacity concerns

12. **Parsed Job Signals** - Structured extraction from job posting text:
    - Technology mentions by category (language, framework, database, cloud, data, devops, security)
    - Role types (backend, frontend, fullstack, data, devops, security, mobile)
    - Seniority distribution — heavy senior/staff hiring signals hard problems; heavy junior hiring signals scaling
    - Use these to cross-reference and validate the detected tech stack

13. **Programmatic Pain Signals** - Automated inferences from combining multiple data sources:
    - Each signal has a rule ID, severity, confidence score, and evidence list
    - These are STARTING POINTS — validate against other data before including in the document
    - Do NOT repeat these verbatim. Synthesize them into your own analysis using the Data Cocktail methodology
    - High-confidence signals (70+) should be strongly considered for Existential Data Points
    - Lower-confidence signals are hypotheses — include only if corroborated by other evidence

14. **Firmographic Data** - Company size, industry, funding, contacts

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
BEFORE SCENARIO ANALYSIS:

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

---

EXISTENTIAL DATA POINTS - CRITICAL:

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

Infrastructure & Security Gaps:
- Security header grade D/F + missing DMARC/SPF = broad security underinvestment
- SSL cert expiring soon without automation = operational process gap
- Multiple cloud providers (DNS + tech stack) = multi-cloud complexity tax
- 6+ analytics/ad tools without a CDP = identity fragmentation and data governance pain
- Heavy data role hiring + single database tech = data infrastructure scaling pressure
- Single cloud vendor across DNS, email, tech stack, CDN = vendor lock-in risk
- Weak security headers + missing email auth + security hiring = compliance gap exposure
- Multiple JS frameworks without CDN = frontend performance debt
- Skewed seniority hiring (all senior or all junior) = organizational imbalance
- 40+ distinct technologies = tool sprawl and governance burden
- Multiple security signals compounding (headers + email + certs) = systemic security underinvestment
- Tech debt + scaling pressure + hiring anomaly compounding = engineering capacity crisis
- Identity fragmentation + tag bloat + marketing mismatch compounding = marketing infrastructure debt
- Product subdomains present but no APM/monitoring detected = observability gap
- Single database + data/backend hiring + no caching layer = database scaling pressure
- Multiple auth/identity providers across subdomains = auth fragmentation and identity management pain

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

Every cocktail should end with a Consequence Chain:
[Observable Behavior] → [Operational Impact] → [Financial/Strategic Consequence]

The consequence chain is what makes the insight actionable for a salesperson. Without it,
you're presenting data. With it, you're presenting a reason to act.

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

CRITICAL — AUDIENCE FILTER FOR TALKING POINTS:
Opening hooks and conversation starters must resonate with the BUYER, not just be technically true. Apply these filters:

1. **Security details are for security buyers only.** Do NOT lead with security header grades, missing DKIM/SPF/DMARC, certificate expiry, or security posture scores UNLESS the seller's product is a security product or the target persona is a security role (CISO, security engineer, etc.). These signals are valuable for the Existential Data Points section but make terrible opening hooks for non-security buyers — they come across as a vulnerability scan, not a sales conversation.

2. **Match signal to buyer's domain.** An engineering leader cares about tech debt, scaling pressure, and hiring gaps. A marketing leader cares about analytics sprawl and identity fragmentation. A CTO cares about architecture and platform decisions. Choose hooks that match what the buyer thinks about daily.

3. **No duplicate signals.** Each opening hook should surface a DIFFERENT insight. Do not use security headers in one hook and DKIM in another — those are the same signal reworded. Spread hooks across different categories (engineering, operations, business, competitive).

4. **Business impact > technical detail.** "50% staff reduction while maintaining 29M users" is a strong hook. "Missing DKIM authentication" is not — unless you are selling email security.
"""

        if target_personas:
            base_prompt += f"""
PERSONA-AWARE HOOKS: The seller targets {target_personas}. Frame opening hooks through the lens of what matters to those personas. For example, for marketing leaders emphasize marketing tech, campaign infrastructure, and attribution signals; for legal ops emphasize compliance, contract management, and regulatory exposure; for engineering leaders emphasize tech stack, scaling, and developer productivity signals.
"""

        base_prompt += """
**Trap-Setting Questions (use to end emails):**
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
PERSONA-AWARE QUESTIONS: Both causes in each two-sided question should resonate with the daily concerns of {target_personas}. Frame root causes in terms these personas would naturally think about.
"""

        base_prompt += """
**Conversation Starters:**
3-5 specific talking points based on verified data. Each should reference something concrete from the research and connect to your product value.

Format: "I noticed [specific observation]. Companies in similar situations often [pattern]. How are you thinking about [related challenge]?"

**Discovery Paths:**
Provide 2-3 ranked conversation angles, ordered by strength of evidence. Each path should:
1. Start from a different verified signal
2. Lead to a pain point the seller's product addresses
3. Include the specific research evidence that supports the path

Format:
- **Path 1 (strongest):** [Signal] → [Pain hypothesis] → [Product connection]
  Evidence: [specific data points]
- **Path 2:** [Signal] → [Pain hypothesis] → [Product connection]
  Evidence: [specific data points]

These give the seller multiple ways into the conversation — if the first angle doesn't resonate,
they have a prepared fallback grounded in different evidence.
"""

        if target_personas:
            base_prompt += f"""
PERSONA-AWARE STARTERS: Reference challenges specific to {target_personas}'s function, not just generic company observations. Connect observations to what these personas care about day-to-day.
"""

        if product_type == "msp":
            base_prompt += """

MSP / IT SERVICES MODIFIER — READ BEFORE SCORING:

You are researching on behalf of a Managed Service Provider (MSP) / IT Services company. This fundamentally changes how you interpret signals:

**Research Focus:**
- Look for location count, multi-site operations, compliance needs (HIPAA, PCI, SOC2, CMMC), absence of internal IT roles, legacy infrastructure, physical operations complexity, and regulated industry indicators.
- Employee count in the 20-500 range with NO dedicated IT staff is a strong signal.

**Pain Inversion:**
- Absence of IT hiring is a POSITIVE pain signal — it means the company likely lacks internal IT capacity and needs managed services.
- Do NOT penalize for lacking technical job postings. For MSP prospects, zero IT roles = maximum pain (they have no one managing their infrastructure).
- Manual processes, compliance gaps, and operational complexity without IT support are critical pain indicators.

**Fit Reframe:**
- Traditional industries with physical operations (manufacturing, distribution, dealerships, healthcare, legal, construction, logistics) are HIGH fit. Do not penalize for lacking digital transformation signals — that IS the opportunity.
- Multi-location businesses score higher — each location multiplies IT complexity.
- Companies in regulated industries (healthcare, finance, legal) that lack IT staff face compliance risk — this is both pain and fit.

**Timing Signals for MSP:**
- Compliance deadlines (HIPAA audits, PCI recertification, cyber insurance renewals) are strong timing signals.
- Lease renewals, office moves, location expansion = infrastructure refresh moments.
- Insurance audit cycles, new regulatory requirements, and security incidents create urgency.
- Leadership changes at non-tech companies often trigger IT modernization.

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

## Before Scenario
Synthesize the Before Scenario for this prospect:

**Problems (Observable):**
- [List specific, verified problems with sources]

**Negative Consequences (Projected):**
- [For each problem: consequence chain showing what happens if unaddressed]

**Current Attempts (Insufficient):**
- [How they're trying to solve it today and why it falls short]

If insufficient data for a full Before Scenario, state what's known and what's missing.
A partial Before Scenario is more valuable than none.

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
- [ ] Existential data points combine multiple data sources (Data Cocktail)
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

**Pain Score (40% weight):**
- How many existential data points did you find?
- Are the problems ones the seller's product directly addresses?
- Is there evidence of active suffering (complaints, long-open roles, tech debt)?

IMPORTANT: You are scoring based on publicly available web data, not insider knowledge. Companies rarely publish their pain directly. Score based on what signals ARE detectable — job postings mentioning problems, tech stack gaps, scaling language on careers pages, etc. A single relevant signal from public data is meaningful and should score in the 50s, not the 30s.

GROWTH-AS-PAIN RULE: Rapid growth is itself a pain signal when the company fits the seller's ICP. Fast-growing companies that match the ICP inevitably face scaling pressure in the seller's domain — even if they haven't publicly complained about it yet. If a company shows strong growth evidence (hiring velocity, funding, revenue growth, product expansion) AND fits the seller's ICP (Fit score would be 60+), treat growth as at least one clear pain signal. This floors the Pain score at 50 minimum. The stronger the growth evidence, the higher within the 50-69 range. Do NOT leave fast-growing ICP-fit companies in the 25-49 "speculative" bucket — growth at scale reliably produces the problems the seller solves.

Calibration anchors:
- 85-100: 3+ compounding pain signals directly addressable by seller's product. Long-open roles (4+ months) in relevant functions. Visible tech debt or scaling failures. Active complaints or incident signals.
- 70-84: 2+ pain signals with product relevance. Job postings mentioning relevant challenges (scaling, migration, performance). Hiring for roles that suggest unresolved problems in the seller's domain.
- 50-69: 1 clear pain signal — a job posting mentioning a relevant problem, tech debt visible in stack, data-intensive operations that imply infrastructure needs, OR rapid growth combined with ICP fit (growth-as-pain rule). This is the EXPECTED range for most prospects where you find something relevant.
- 25-49: Speculative pain only. No job postings mention relevant problems. Pain is inferred purely from industry or company type, not observed. NOTE: If the company is clearly growing fast and fits the ICP, this bucket is wrong — apply the growth-as-pain rule and score 50+.
- 0-24: No observable pain signals whatsoever. No relevant hiring, no tech indicators, nothing to suggest they need the seller's product.

**Fit Score (35% weight):**
- Does their company size/industry match the seller's ICP?
- Are the right personas (target level + function) present?
- Is there competitor presence that creates displacement opportunity?
- Does their tech stack align with integration requirements?

Calibration anchors:
- 85-100: Exact ICP match — right industry, right company size, target personas confirmed in job postings, tech stack aligns perfectly. Competitor presence creates clear displacement opportunity. REQUIRES confirmed firmographic data to score here.
- 70-84: Strong ICP overlap — most dimensions match. Right industry, reasonable size, some target personas visible. Tech stack suggests relevance.
- 45-69: Partial fit — adjacent industry or size is outside sweet spot. Some tech stack overlap but not core. Few or no target personas visible.
- 20-44: Weak fit — different industry, wrong size, no persona signals. Would require significant stretching of ICP definition.
- 0-19: No fit — completely outside ICP. Different market, wrong tech ecosystem, no relevant personas. A consumer app, a restaurant, a sports team with no data infrastructure needs.

IMPORTANT: Without confirmed firmographic data (headcount, funding, revenue from SEC EDGAR filings or other verified sources), cap Fit at 84 maximum. You may infer fit from strong indirect signals (job postings, tech stack, industry presence) up to 84. Scores above 84 require confirmed data. A networking company is not an 88 Fit just because they are "enterprise tech."

**Timing Score (25% weight):**
- Is there a funding event, reorg, or leadership change creating urgency?
- Are there roles open 3+ months suggesting unresolved problems?
- Is there a regulatory deadline or competitive threat with a timeline?
- Are they actively evaluating solutions (RFP signals, comparison content)?

IMPORTANT: Active hiring and recent product launches ARE timing signals. A company that is actively posting technical roles and shipping new features is in a building phase — that's a real window. Don't require a funding round or leadership change to score above 50.

Calibration anchors:
- 85-100: Multiple concurrent urgency signals — recent funding + hiring spike + leadership change. Active vendor evaluation. Deadline-driven need.
- 70-84: Clear urgency — recent funding OR significant hiring spike OR leadership change. Evidence of active building/transformation.
- 50-69: Active building phase — steady technical hiring, recent product launches, or platform expansion. The company is investing and making decisions. This is the EXPECTED range for growing companies without a specific urgency trigger.
- 25-49: Minimal activity — limited hiring, no recent news, no visible investment. Company appears stable but not actively building.
- 0-24: Anti-timing — recent layoffs, budget cuts, hiring freeze, or sunsetting product. OR: zero timing signals of any kind found.

CONCRETE EXAMPLE (for a database product seller):
- A mid-market fintech company (confirmed 500 employees via SEC filings) hiring 3 backend engineers and 1 data engineer, with job postings open 4+ months mentioning "scaling challenges" and "migration from legacy systems," recently raised Series C, and using a competitor's product visible in their tech stack → Pain: 88, Fit: 85, Timing: 82, Composite: 86
- A SaaS platform (enterprise customers, right industry) hiring multiple backend engineers with postings mentioning "search infrastructure" and "recommendation systems," active product launches, but no confirmed database pain or long-open roles → Pain: 57, Fit: 76, Timing: 61, Composite: 64
- A regional bank with no technical hiring, no visible API infrastructure, no recent funding or leadership changes, and steady-state operations → Pain: 27, Fit: 48, Timing: 23, Composite: 33
- A fast-growing enterprise healthcare company (strong ICP fit, data-intensive operations, recent product expansion, active hiring) but no explicit pain signals in job postings or public content → Pain: 53, Fit: 72, Timing: 57, Composite: 60. Growth-as-pain rule applies: rapid growth + ICP fit floors pain at 50+, not the 38 it would get from speculative inference alone.
- A baseball analytics company with data-intensive operations but no database pain signals, MySQL in their stack, no technical hiring, private company → Pain: 33, Fit: 41, Timing: 24, Composite: 33

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

        return base_prompt

    def _build_user_prompt(
        self,
        company_url: str,
        scraped: ScrapedContent,
        tech_by_domain: Optional[dict[str, TechStack]] = None,
        dns_profile: Optional[DNSProfile] = None,
        ssl_profile: Optional[SSLProfile] = None,
        security_posture: Optional[SecurityPosture] = None,
        robots_signals: Optional[RobotsSignals] = None,
        job_signals: Optional[JobSignals] = None,
        pain_inferences: Optional[list[PainInference]] = None,
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

        if dns_profile:
            sections.append("## DNS Infrastructure Signals")
            if dns_profile.ns_provider:
                sections.append(f"- NS Provider: {dns_profile.ns_provider}")
            if dns_profile.mx_provider:
                sections.append(f"- Email Provider: {dns_profile.mx_provider}")
            sections.append(f"- SPF: {'Present' if dns_profile.has_spf else 'Missing'}")
            sections.append(f"- DKIM: {'Present' if dns_profile.has_dkim else 'Missing'}")
            sections.append(f"- DMARC: {'Present' if dns_profile.has_dmarc else 'Missing'}" +
                          (f" (policy: {dns_profile.dmarc_policy})" if dns_profile.dmarc_policy else ""))
            if dns_profile.cloud_provider_hints:
                sections.append(f"- Cloud hints: {', '.join(dns_profile.cloud_provider_hints)}")
            sections.append("")

        if ssl_profile:
            sections.append("## SSL/TLS Certificate")
            if ssl_profile.issuer:
                sections.append(f"- Issuer: {ssl_profile.issuer}")
            if ssl_profile.expiry_days is not None:
                sections.append(f"- Expires in: {ssl_profile.expiry_days} days")
            sections.append(f"- SAN count: {ssl_profile.san_count}")
            sections.append(f"- Wildcard: {'Yes' if ssl_profile.is_wildcard else 'No'}")
            sections.append(f"- Automated renewal: {'Likely' if ssl_profile.automation_inferred else 'Unknown'}")
            sections.append("")

        if security_posture:
            sections.append("## Security Header Analysis")
            sections.append(f"- Grade: {security_posture.grade} ({security_posture.score}/6)")
            if security_posture.present:
                sections.append(f"- Present: {', '.join(security_posture.present)}")
            if security_posture.missing:
                sections.append(f"- Missing: {', '.join(security_posture.missing)}")
            sections.append("")

        if robots_signals:
            sections.append("## Robots.txt Signals")
            if robots_signals.api_paths:
                sections.append(f"- API paths: {', '.join(robots_signals.api_paths)}")
            if robots_signals.admin_paths:
                sections.append(f"- Admin paths: {', '.join(robots_signals.admin_paths)}")
            if robots_signals.crawl_delay is not None:
                sections.append(f"- Crawl delay: {robots_signals.crawl_delay}")
            sections.append("")

        if job_signals and job_signals.tech_mentions:
            sections.append("## Parsed Job Signals")
            by_cat: dict[str, list[str]] = {}
            for tm in job_signals.tech_mentions:
                by_cat.setdefault(tm.category, []).append(f"{tm.name} (x{tm.count})")
            for cat, items in by_cat.items():
                sections.append(f"- {cat}: {', '.join(items)}")
            if job_signals.role_types:
                sections.append(f"- Role types: {', '.join(job_signals.role_types)}")
            if job_signals.seniority_distribution:
                seniority_str = ", ".join(f"{k}: {v}" for k, v in job_signals.seniority_distribution.items())
                sections.append(f"- Seniority: {seniority_str}")
            sections.append("")

        if pain_inferences:
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
            for pi in pain_inferences:
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

        if scraped.firmographics:
            sections.append("## CONFIRMED Firmographic Data (from connected data provider)")
            sections.append(scraped.firmographics)
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
        product_type: str = "saas",
        dns_profile: Optional[DNSProfile] = None,
        ssl_profile: Optional[SSLProfile] = None,
        security_posture: Optional[SecurityPosture] = None,
        robots_signals: Optional[RobotsSignals] = None,
        job_signals: Optional[JobSignals] = None,
        pain_inferences: Optional[list[PainInference]] = None,
    ) -> ResearchDocument:
        """Generate the full Account Research Document using Claude."""
        system_prompt = self._build_system_prompt(
            product_context, retrieved_materials, seller_company,
            target_personas=target_personas, target_industries=target_industries,
            problems_solved=problems_solved, product_type=product_type,
        )
        user_prompt = self._build_user_prompt(
            company_url, scraped, tech_by_domain,
            dns_profile=dns_profile, ssl_profile=ssl_profile,
            security_posture=security_posture, robots_signals=robots_signals,
            job_signals=job_signals, pain_inferences=pain_inferences,
        )

        model = self.settings.research_model
        response = await self.client.chat.completions.create(
            model=model,
            max_tokens=16000,
            temperature=1.0,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )

        full_markdown = response.choices[0].message.content or ""
        thinking_content = ""
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
            before_scenario=sections.get("before_scenario", ""),
            pvp_seed=sections.get("pvp_seed", ""),
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
            "recent news & press": "recent_news",
            "recent news and press": "recent_news",
            "recent news": "recent_news",
            "key contacts": "key_contacts",
            "contacts": "key_contacts",
            "information gaps": "information_gaps",
            "before scenario": "before_scenario",
            "pvp seed": "pvp_seed",
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
