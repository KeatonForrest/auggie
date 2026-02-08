"""writing.py - AI-powered outreach generation using Claude Sonnet."""

import re
from openai import AsyncOpenAI
from typing import Optional
from models import ResearchDocument
from config import get_settings


class WritingService:
    """Service for generating outreach emails from research documents."""

    def __init__(self):
        self.settings = get_settings()
        self.client = AsyncOpenAI(
            api_key=self.settings.openrouter_api_key,
            base_url="https://openrouter.ai/api/v1",
        )

    def _build_report(self, document: ResearchDocument, product_context: str, retrieved_materials: str = "",
                       seller_company: str = "", problems_solved: str = "") -> str:
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
        if seller_company:
            sections.append(f"**Company:** {seller_company}")
        sections.append(product_context)

        if problems_solved:
            sections.append("")
            sections.append("## Specific Problems We Solve")
            sections.append(f"Align email angles to these problems when the research shows a match: {problems_solved}")

        if retrieved_materials:
            sections.append("")
            sections.append("## Sales Materials (Case Studies, Battle Cards, Proof Points)")
            sections.append("Use these to reference specific results, metrics, and customer stories in your emails.")
            sections.append(retrieved_materials)

        return "\n".join(sections)

    def _build_prompt(self, report: str, opportunity_score: Optional[int] = None, product_type: str = "saas") -> str:
        """Build the full prompt with the report inserted."""
        low_confidence_block = ""
        low_confidence_closing = ""
        if opportunity_score is not None and opportunity_score < 50:
            low_confidence_block = f"""
**LOW-CONFIDENCE RESEARCH -- PARTIAL-SIGNAL MODE**

The research score for this prospect is {opportunity_score}/100. The data is thin, ambiguous, or unconfirmed.

You MUST use partial-signal patterns for this sequence:
- Do NOT use "that combination usually means" or similar confident framing
- Name what you observed and explicitly acknowledge what you don't know
- Offer value conditionally: "If X is true, here's something useful"
- Give permission to ignore: "If this isn't relevant, no worries"
- Position insights as benchmarks, not diagnoses
- Use "a company in a similar situation" framing in ENGAGE, not definitive case studies
- Frame the ASK as "yours regardless" or "useful either way"
- Lead with business initiatives, product launches, or market moves -- not tech stack details
- Never reference what your research did or didn't uncover. Talk about what the prospect is DOING, not what your search turned up. Do not narrate the research process.
- If you only have partial signals, lead with the business activity and pivot to the value question: "You're expanding into X -- curious whether Y is on your radar."
- Never use condescending qualifiers about their stack: "basic", "simple", "limited", "rudimentary", "might work fine now", "works fine for now". Describe what they have neutrally without grading it.
- Do NOT use these phrases or similar: "no obvious", "lacking", "without any", "missing", "doesn't appear to have", "I couldn't find", "worth knowing the pattern"

Refer to Section B (Examples 41-50) for tone and structure. Those are your primary models for this sequence.

---

"""
            low_confidence_closing = """

---

**FINAL CHECK -- PARTIAL-SIGNAL MODE**

BEFORE outputting your emails, re-read the PARTIAL-SIGNAL MODE block at the top. Then scan every sentence you wrote for:
- Banned phrases: "no obvious", "lacking", "without any", "missing", "doesn't appear to have", "I couldn't find", "that combination"
- Any sentence describing what your research did NOT find -- rewrite to state only what you observed
- Any condescending framing: "basic", "simple", "limited", "rudimentary", "might work fine", "works fine for now", "worth knowing" -- describe their stack neutrally without grading it

If any violations appear, rewrite those sentences before outputting. Do not output a first draft.
"""
        msp_block = ""
        if product_type == "msp":
            msp_block = (
                "**MSP / IT SERVICES FRAMING -- APPLY TO ALL EMAILS:**\n"
                "\n"
                "- Lead with operational complexity and the burden of managing IT alongside core business. The prospect runs a non-tech company and IT is a distraction from their actual work.\n"
                "- Frame around reliability, compliance, and freeing up leadership attention -- not digital transformation or innovation.\n"
                "- The prospect is not a tech buyer -- avoid technical jargon entirely. Frame everything in business terms: uptime, risk, cost predictability, compliance peace of mind.\n"
                "- Reference pain they feel daily: systems going down, employees calling the owner about printer/email issues, compliance audit anxiety, not knowing if backups actually work.\n"
                "- Position managed services as removing a burden, not adding a capability.\n"
                "\n"
                "---\n"
                "\n"
            )
        prompt = f"""**CRITICAL: WORD LIMITS ARE MANDATORY**

Count words before submitting each email. If over the limit, rewrite shorter.

- Email 1: 75 words max
- Email 2: 100 words max
- Email 3: 60 words max

These are requirements, not guidelines.

---

{low_confidence_block}{msp_block}You are an expert at crafting Personalized Value Propositions (PVPs) for B2B sales outreach.

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

**CRITICAL: NEVER name specific companies in case studies or examples.**
When referencing how another company solved a similar problem, describe them by their vertical or industry instead. Examples:
- "Another retailer faced the same challenge"
- "A healthcare provider saw something similar"
- "A B2B software company experienced this too"
Do NOT invent company names or attribute results to real named companies. The prospect cannot verify these claims, and fabricated references destroy credibility.

**CRITICAL: Write like a peer, not a researcher.**
- NEVER cite sources: "according to SEC filings", "based on your 10-K", "your job postings show", "per your earnings call". State observations as things you noticed, not things you researched.
- NEVER use "that combination" or "that combination usually means" as a transition phrase. It is a crutch. Find a direct, natural bridge between the observation and the implication.

**CRITICAL: Frame challenges as opportunities, not diagnoses.**
- You are not a doctor listing symptoms. You are a peer who sees where they're headed and wants to help them get there faster.
- Do NOT dwell on what's going wrong: "profit declines", "already challenging", "the timing rarely feels right", "struggling with"
- DO frame around what's possible: "you're in a position to", "companies at this inflection point", "the teams moving fastest right now"
- The prospect already knows their problems. Show them you understand the opportunity inside those problems.

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
- NEVER use "that combination usually" or "that combination" as a transition -- find a more natural bridge
- NEVER cite your sources ("according to SEC filings", "based on your job postings", "your 10-K shows"). State what's happening as common knowledge. If you wouldn't say "according to SEC filings" in a real conversation, don't write it.

Structure:
- Lead with the BUSINESS initiative or outcome they care about (product launch, market move, growth milestone)
- Connect it to the friction or tradeoff companies in that position face
- Close with a pattern or implication that earns curiosity

**CRITICAL: Lead with business, not technology.**
- DO NOT open with tech stack observations ("I noticed your site runs jQuery", "your domains show Bootstrap")
- DO NOT list specific technologies, frameworks, or languages in the opening line
- Technology can appear as brief supporting context mid-email, but the opener and closer must be about the business problem, initiative, or outcome
- Think "you're launching X" not "your stack uses Y"

Bad: "I noticed your product domains show jQuery and Bootstrap across the board while you're hiring AI Engineers."
Good: "You're launching Deal Intelligence while scaling your AI team -- the companies shipping AI products fastest have found a way to avoid the frontend rewrite that usually slows things down."

Bad: "I noticed you're running Postgres and Redis while migrating to microservices."
Good: "You're breaking your monolith into services while keeping release velocity up. Most teams in that transition hit a data layer bottleneck they don't see coming."

Example (65 words):
"You are rolling out AI agents across five use cases while expanding the engineering team to keep up. That pace usually forces a choice: expensive vertical scaling or a long re-architecture project that slows product delivery.

The companies shipping fastest right now have found a third path that avoids both. The pattern looks a lot like what you are building toward."

---

**Email 2 - ENGAGE (The Proof)**

Job: Prove expertise. Show you have solved this before. Make them curious how.

Constraints:
- 100 words max
- One quantified outcome from a similar company (describe by vertical, NEVER by name)
- Do NOT explain how the outcome was achieved
- No product mentions
- End with a statement that connects to them

Example (78 words):
"An AI infrastructure company hit the same wall. They were shipping fast but every new use case meant more custom plumbing to keep performance up. Engineering headcount was growing faster than product output.

They fixed it in 8 weeks. Cut time-to-ship by 60%. Stopped their backend hiring surge. Model performance improved 3x while infrastructure costs dropped.

Your AI agents initiative has the same shape. Five use cases, growing team, and velocity pressure that keeps rising."

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

**ADDITIONAL PVP EXAMPLES**

The following 50 examples show the PEA framework in action. They are split into two sections:

**Section A (Examples 1-40): Full-Confidence PVPs** -- Multiple confirming signals triangulate to a specific pain. Use these as patterns for standard outreach.

**Section B (Examples 41-50): Partial-Signal PVPs** -- Only one signal available, signal is ambiguous, stale, or lacks company-specific confirmation. These demonstrate how to write valuable sequences when data is incomplete.

---

**SECTION A: FULL-CONFIDENCE PVP EXAMPLES**

**PART 1: SaaS HORIZONTAL (5)**

Example 1: HR Tech (Time-to-Hire Pain)
Target: VP of Talent at a Series B SaaS company
Existential Data Point: Time-to-hire > 45 days
Data Cocktail: 47 open roles on LinkedIn + 12 posted 60+ days ago + Glassdoor reviews mentioning "slow hiring process"

Email 1 - PREVIEW
Subject: 12 roles open since November
I noticed you have 47 open roles, and 12 of them have been posted for over 60 days. That pattern usually means either your pipeline is thin or candidates are dropping between stages.
Either way, your hiring managers are probably losing confidence. Reqs that age past 45 days rarely close with the original candidate pool. The companies closing roles fastest right now have figured out where their funnel leaks.

Email 2 - ENGAGE
Subject: How a mid-market HR tech company cut time-to-hire by 40%
A mid-market HR tech company had the same problem last year. Senior roles sitting open for 60+ days. Hiring managers frustrated. Recruiters buried in unqualified applicants.
They identified two leaks: 80% of drop-off happened between screen and onsite, and their job posts attracted high volume but low fit. They fixed both without adding headcount.
Time-to-hire dropped from 52 days to 31. Offer acceptance jumped to 89%. Your open role count and tenure pattern looks similar to where they started.

Email 3 - ASK
Subject: Quick funnel audit
Happy to pull your public job data and show where candidates are likely dropping. Takes 15 minutes and you keep the analysis.
We build the recruiting intelligence layer that helped a mid-market HR tech company find those leaks. Worth a look?

---

Example 2: RevOps / Sales Tech (Pipeline Coverage Pain)
Target: VP of Revenue Operations at a growth-stage B2B company
Existential Data Point: Pipeline coverage < 3x
Data Cocktail: Job posting for "Senior Sales Ops Analyst" mentioning "pipeline visibility" + LinkedIn posts from CRO about "big Q4 push" + 3 new AE hires in last 60 days

Email 1 - PREVIEW
Subject: Pipeline visibility before Q4
I saw your CRO's post about the Q4 push and noticed you just hired 3 AEs while posting for a Sales Ops Analyst focused on pipeline visibility. That combination usually means coverage is tight and forecasting is getting harder.
Most RevOps teams in this spot are flying blind on which deals will actually close. The companies with clean forecasts have figured out how to score pipeline quality, not just quantity.

Email 2 - ENGAGE
Subject: How a revenue intelligence company fixed their Q4 forecast
A revenue intelligence company hit this wall two years ago. New AEs ramping, pipeline looked healthy on paper, but win rates told a different story. Their coverage was 3.5x but real coverage was closer to 2x when they scored for deal quality.
They built a system that flagged at-risk deals 30 days earlier. Q4 forecast accuracy went from 67% to 91%. They stopped sandbagging and stopped surprising the board.
Your hiring pattern and Q4 pressure look like the same setup.

Email 3 - ASK
Subject: Pipeline quality scorecard
I can put together a quick read on your current pipeline mix based on public signals. Shows where the real coverage gaps likely are.
We help RevOps teams build the deal-scoring layer that fixed a revenue intelligence company's forecast. Worth 15 minutes?

---

Example 3: FinOps / Cloud Cost (Cloud Spend Pain)
Target: VP of Engineering or Head of Platform at a scaling startup
Existential Data Point: Cloud cost growing faster than revenue
Data Cocktail: AWS job certifications on team LinkedIn profiles + Series C announcement ($80M) + Job posting for "FinOps Engineer"

Email 1 - PREVIEW
Subject: Post-Series C cloud math
Congrats on the $80M round. I noticed you just posted for a FinOps Engineer. That role usually shows up when cloud costs have crossed a threshold that makes finance nervous.
Most companies at your stage see cloud growing 1.5-2x faster than revenue. The ones who get ahead of it find 25-40% waste hiding in plain sight. The ones who wait end up in emergency optimization mode six months later.

Email 2 - ENGAGE
Subject: How a fast-growing fintech company found $2M in cloud waste
A fast-growing fintech company hit this inflection after their Series C. Cloud bill growing faster than revenue. Engineering blamed product complexity. Finance blamed engineering. Nobody had visibility into what was actually driving cost.
They ran a 3-week audit and found $2M in annual waste. Orphaned resources, oversized instances, and reserved capacity they never used. No performance trade-offs. Pure savings.
Your FinOps posting and funding stage look like the same pattern.

Email 3 - ASK
Subject: Quick cloud audit
Happy to pull your public infrastructure footprint and show where the waste likely is. Takes 20 minutes and you keep the analysis.
We build the cost visibility layer that helped a fast-growing fintech company find that $2M. Worth a look?

---

Example 4: Customer Success (Time-to-Value Pain)
Target: VP of Customer Success at a B2B SaaS company
Existential Data Point: Time-to-value > 30 days
Data Cocktail: G2 reviews mentioning "steep learning curve" + Job posting for "Onboarding Manager" + NPS score visible on website showing decline

Email 1 - PREVIEW
Subject: Onboarding before expansion
I noticed you're hiring an Onboarding Manager and saw a few G2 reviews mentioning a steep learning curve. That combination usually means time-to-value has stretched past where it should be.
When onboarding takes longer than 30 days, expansion conversations get pushed out. CSMs spend time on setup instead of growth. The companies fixing this have found that 80% of delayed value comes from 2-3 specific friction points.

Email 2 - ENGAGE
Subject: How a productivity software company cut onboarding time in half
A productivity software company had the same pattern. Powerful product, but new customers took 45+ days to hit their first value milestone. Expansion rates lagged. CSMs were stuck in implementation mode.
They mapped the journey and found three friction points causing 70% of delays. Fixed them without changing the product. Time-to-value dropped from 45 days to 18. Expansion revenue jumped 34% the next quarter.
Your G2 feedback and hiring pattern look like the same setup.

Email 3 - ASK
Subject: Value milestone audit
Happy to map your current onboarding flow and show where customers likely get stuck. Takes 20 minutes and you keep the analysis.
We build the customer journey layer that helped a productivity software company find those friction points. Worth a conversation?

---

Example 5: Dev Tools (Build Time Pain)
Target: VP of Engineering or Head of Platform at a scaling engineering org
Existential Data Point: Build/deploy time > 15 minutes
Data Cocktail: Job posting for "Developer Experience Engineer" + GitHub repo showing CI workflow complexity + Engineering blog post mentioning "developer productivity"

Email 1 - PREVIEW
Subject: Developer experience before velocity
I saw your posting for a Developer Experience Engineer and your recent blog post on productivity. That combination usually means build times or deploy friction have crossed a pain threshold.
When builds take longer than 15 minutes, developers lose flow state. PRs sit longer. Release frequency drops. The companies fixing this have found that most build time is wasted on things that don't need to run.

Email 2 - ENGAGE
Subject: How a high-scale payments platform cut build times by 70%
A high-scale payments platform hit this wall at scale. Builds took 20+ minutes. Developers context-switched while waiting. Deploy frequency slowed. Eng leadership knew it was a problem but couldn't see where the time went.
They instrumented their pipeline and found 70% of build time was running tests that hadn't changed. They fixed it in 6 weeks. Builds dropped to under 5 minutes. Deploy frequency doubled. Developer satisfaction scores jumped.
Your DevEx hiring and blog focus look like the same pattern.

Email 3 - ASK
Subject: Build pipeline audit
Happy to look at your public CI config and show where time is likely being wasted. Takes 15 minutes and you keep the analysis.
We build the developer productivity layer that helped a high-scale payments platform find that 70%. Worth a look?

---

**PART 2: SaaS VERTICAL (8)**

Example 6: Security (MTTD Pain)
Target: CISO or VP of Security at a mid-market company
Existential Data Point: Mean time to detect > 200 days
Data Cocktail: Job posting for "Security Analyst" mentioning SIEM + LinkedIn shows SOC team of 3 + recent compliance certification (SOC 2)

Email 1 - PREVIEW
Subject: SOC capacity and detection time
I noticed you recently completed SOC 2 and you're hiring another Security Analyst. Your current team looks like 3 people covering a growing attack surface.
At that ratio, most security teams see detection times stretch past 200 days. The math just doesn't work. The companies catching threats faster have stopped trying to monitor everything and started prioritizing what actually matters.

Email 2 - ENGAGE
Subject: How a mid-market security company cut detection time by 60%
A mid-market security company had the same problem. Small SOC team, expanding infrastructure, alert fatigue burying real threats. Their MTTD had crept past 180 days without anyone noticing.
They rebuilt their detection priorities in 4 weeks. Focused on 12 critical patterns instead of thousands. MTTD dropped to 72 days. Alert volume dropped 80%. Same team size, completely different coverage.
Your SOC ratio and growth stage look like the same setup.

Email 3 - ASK
Subject: Detection priority audit
Happy to map your current alert sources and show which ones actually matter for your threat profile. Takes 20 minutes and you keep the analysis.
We build the detection layer that helped a mid-market security company focus. Worth a look?

---

Example 7: Compliance / GRC (Audit Prep Pain)
Target: VP of Compliance or Head of GRC
Existential Data Point: Audit prep time > 4 weeks
Data Cocktail: Job posting for "Compliance Manager" + multiple certifications listed on website (SOC 2, ISO, HIPAA) + Series B funding

Email 1 - PREVIEW
Subject: Audit prep at scale
I noticed you're hiring a Compliance Manager and you're maintaining SOC 2, ISO, and HIPAA simultaneously. That combination usually means audit prep has become a quarterly fire drill.
Most compliance teams at your stage spend 4-6 weeks preparing for each audit. The companies who've cut that to days have stopped treating compliance as a point-in-time exercise.

Email 2 - ENGAGE
Subject: How a compliance automation company cut audit prep from 6 weeks to 3 days
A compliance automation company faced their own compliance wall before building for others. Three certifications, quarterly audits, and a team stretched thin. Audit prep consumed 6 weeks every cycle.
They built continuous monitoring that kept evidence current. Prep time dropped from 6 weeks to 3 days. Findings dropped to near zero. The compliance team shifted from evidence gathering to risk management.
Your certification count and hiring pattern look like the same setup.

Email 3 - ASK
Subject: Audit readiness snapshot
Happy to map your current certification requirements and show where evidence gaps likely are. Takes 20 minutes and you keep the analysis.
We build the continuous compliance layer that made a compliance automation company's own audits painless. Worth a look?

---

Example 8: Product / PLG (Free-to-Paid Conversion Pain)
Target: VP of Product or Head of Growth
Existential Data Point: Free-to-paid conversion < 3%
Data Cocktail: Generous free tier visible on pricing page + job posting for "Growth Product Manager" + product analytics tool in stack (Amplitude/Mixpanel)

Email 1 - PREVIEW
Subject: Free tier economics
I noticed your free tier is generous and you're hiring a Growth PM focused on conversion. That combination usually means free-to-paid is below where it needs to be.
When conversion sits under 3%, acquisition spend doesn't pay back. The companies fixing this have found that most free users never hit the feature that would make them pay. They don't have a conversion problem. They have an activation problem.

Email 2 - ENGAGE
Subject: How a video communication company 4x'd their conversion rate
A video communication company had the same math problem. Millions of free users, but conversion sat at 1.8%. Growth team tried pricing experiments. Didn't move. Tried feature gating. Made it worse.
They mapped user journeys and found 70% of free users never used the feature that drove upgrades. They rebuilt onboarding around that single action. Conversion jumped to 7.2% in one quarter.
Your free tier structure and growth hiring look like the same pattern.

Email 3 - ASK
Subject: Activation audit
Happy to map your free tier journey and show where users likely drop before hitting the upgrade trigger. Takes 15 minutes and you keep the analysis.
We build the product intelligence layer that helped a video communication company find their activation gap. Worth a look?

---

Example 9: MarTech (CAC Payback Pain)
Target: VP of Marketing or Head of Demand Gen
Existential Data Point: CAC payback > 18 months
Data Cocktail: Heavy paid ad presence (LinkedIn, Google) + job posting for "Performance Marketing Manager" + Series B funding with growth expectations

Email 1 - PREVIEW
Subject: Paid spend and payback math
I noticed your paid presence is heavy on LinkedIn and Google, and you're hiring a Performance Marketing Manager. That combination usually means CAC payback has stretched longer than the board wants.
When payback crosses 18 months, you can't scale spend without burning cash. The companies fixing this have found that channel mix is usually the symptom, not the cause. The real problem is conversion rate by segment.

Email 2 - ENGAGE
Subject: How a website platform company cut CAC payback by 60%
A website platform company hit this wall post-Series B. Paid was working but payback had stretched to 22 months. Board wanted growth but the math didn't support more spend.
They stopped optimizing channels and started optimizing segments. Found that 3 ICPs converted at 4x the rate of the rest. Shifted 70% of spend to those segments. Payback dropped from 22 months to 9. Growth accelerated without burning more cash.
Your paid footprint and hiring suggest the same pattern.

Email 3 - ASK
Subject: Segment payback analysis
Happy to pull your public ad presence and show which segments likely have the best payback math. Takes 15 minutes and you keep the analysis.
We build the attribution layer that helped a website platform company find their efficient segments. Worth a conversation?

---

Example 10: E-commerce Platform (Cart Abandonment Pain)
Target: VP of E-commerce or Head of Digital
Existential Data Point: Cart abandonment > 75%
Data Cocktail: Shopify Plus or Magento in stack + job posting for "Conversion Rate Optimization Specialist" + high traffic visible via SimilarWeb

Email 1 - PREVIEW
Subject: Traffic vs conversion math
I noticed you're getting strong traffic and hiring a CRO Specialist. That combination usually means cart abandonment is eating your margins.
When abandonment crosses 75%, your paid traffic ROI collapses. You're paying to fill a leaky bucket. The companies fixing this have found that most abandonment happens at 2-3 predictable friction points, not spread evenly across the funnel.

Email 2 - ENGAGE
Subject: How a fast-growing DTC brand dropped abandonment by 35%
A fast-growing DTC brand had the same leak. Strong brand, strong traffic, but 78% cart abandonment. They tried discount pop-ups. Made it worse. Tried urgency messaging. Marginal improvement.
They instrumented the checkout flow and found 60% of abandonment happened at shipping calculation. One friction point. They fixed it with real-time shipping estimates. Abandonment dropped to 51%. Revenue per session jumped 28%.
Your traffic and CRO hiring suggest the same pattern.

Email 3 - ASK
Subject: Checkout friction audit
Happy to walk through your checkout flow and show where abandonment likely spikes. Takes 15 minutes and you keep the analysis.
We build the conversion layer that helped a fast-growing DTC brand find their friction point. Worth a look?

---

Example 11: Insurance Tech (Loss Ratio Pain)
Target: VP of Underwriting or Chief Actuary
Existential Data Point: Loss ratio > 70%
Data Cocktail: Job posting for "Pricing Analyst" + recent rate filing visible in state records + competitor just raised rates

Email 1 - PREVIEW
Subject: Loss ratio and pricing pressure
I noticed your recent rate filing and the Pricing Analyst role you're hiring. That combination usually means loss ratio has crept above where it should be.
When loss ratio crosses 70%, you're choosing between raising rates and losing share, or holding rates and losing margin. The companies breaking this trade-off have found that the problem isn't pricing. It's risk selection.

Email 2 - ENGAGE
Subject: How a digital-first insurance company improved loss ratio by 15 points
A digital-first insurance company faced the same squeeze. Loss ratio at 73%. Competitors raising rates. Growth team wanted volume. Finance wanted margin. Neither could win.
They rebuilt their risk scoring model to catch bad risks at quote, not at claim. Loss ratio dropped from 73% to 58% over two quarters. They gained share while competitors raised rates.
Your filing pattern and hiring suggest the same pressure.

Email 3 - ASK
Subject: Risk selection audit
Happy to look at your current underwriting criteria and show where adverse selection likely hides. Takes 20 minutes and you keep the analysis.
We build the risk intelligence layer that helped a digital-first insurance company fix their loss ratio. Worth a look?

---

Example 12: Healthcare Tech (Claims Denial Pain)
Target: VP of Revenue Cycle or CFO at a health system
Existential Data Point: Claims denial rate > 10%
Data Cocktail: Job posting for "Denial Management Specialist" + CMS quality rating visible + recent acquisition of another practice

Email 1 - PREVIEW
Subject: Denial rate after acquisition
I noticed you recently acquired two practices and you're hiring a Denial Management Specialist. That combination usually means denial rates have spiked past acceptable levels.
When denials cross 10%, cash flow becomes unpredictable. Staff spend more time on rework than new claims. The organizations fixing this have found that 80% of denials come from 5 preventable root causes.

Email 2 - ENGAGE
Subject: How a multi-location healthcare provider cut denials by 65%
A multi-location healthcare provider faced this after their expansion. Different practices, different billing systems, denial rate at 14%. Revenue cycle became a cash flow crisis.
They mapped every denial to root cause and found 5 patterns driving 80% of rework. Fixed those at submission. Denial rate dropped from 14% to 5%. Cash collection improved by 23%. Same staff, completely different outcomes.
Your acquisition pattern and hiring look like the same setup.

Email 3 - ASK
Subject: Denial root cause analysis
Happy to map your payer mix and show where denials likely cluster. Takes 20 minutes and you keep the analysis.
We build the claims intelligence layer that helped a multi-location healthcare provider find their root causes. Worth a conversation?

---

Example 13: Fintech (Transaction Fraud Pain)
Target: VP of Risk or Head of Trust & Safety
Existential Data Point: Transaction fraud > 0.1%
Data Cocktail: Job posting for "Fraud Analyst" + app store reviews mentioning account takeover + rapid user growth announced

Email 1 - PREVIEW
Subject: Fraud rate at scale
I saw your growth numbers and noticed you're hiring multiple Fraud Analysts. A few app reviews mention account issues. That combination usually means fraud rate is climbing faster than your detection can keep up.
When fraud crosses 0.1%, regulators notice and payment partners get nervous. The companies staying ahead of this have stopped writing rules and started predicting fraud patterns before they spread.

Email 2 - ENGAGE
Subject: How a high-growth neobank kept fraud at 0.03% through 5x growth
A high-growth neobank faced this during their growth surge. User base 5x'd in 18 months. Fraud patterns evolved faster than rules could catch. Rate was creeping toward 0.15%.
They shifted from rule-based to pattern-based detection. Models that learned from every transaction instead of waiting for new rules. Fraud rate dropped to 0.03% and stayed there through continued growth. False positives dropped 60%.
Your growth pace and fraud hiring look like the same pattern.

Email 3 - ASK
Subject: Fraud pattern analysis
Happy to look at your current transaction flow and show where fraud likely concentrates. Takes 15 minutes and you keep the analysis.
We build the detection layer that helped a high-growth neobank stay at 0.03%. Worth a look?

---

**PART 3: MORE SaaS VERTICAL (7)**

Example 14: Legal Tech (Contract Cycle Time Pain)
Target: General Counsel or VP of Legal Ops
Existential Data Point: Contract cycle time > 30 days
Data Cocktail: Job posting for "Legal Operations Manager" + Salesforce in tech stack + recent funding round requiring fast deal velocity

Email 1 - PREVIEW
Subject: Contract velocity post-funding
Congrats on the round. I noticed you're hiring a Legal Ops Manager and running deals through Salesforce. That combination usually means contract cycle time has become a bottleneck to revenue.
When contracts take longer than 30 days, sales cycles extend and quarter-end becomes chaos. The companies moving faster have found that 80% of delay comes from redlines that shouldn't need legal review at all.

Email 2 - ENGAGE
Subject: How a cloud software company cut contract time from 28 days to 5
A cloud software company hit this wall during their growth phase. Legal was reviewing every contract. Sales was frustrated. Deal slippage became normal.
They built a self-serve layer for standard terms. 85% of contracts closed without legal touch. Cycle time dropped from 28 days to 5. Legal shifted from bottleneck to strategic advisor. Sales stopped sandbagging close dates.
Your funding pace and legal ops hiring suggest the same pressure.

Email 3 - ASK
Subject: Contract bottleneck analysis
Happy to map your current deal flow and show where legal delays likely cluster. Takes 15 minutes and you keep the analysis.
We build the contract automation layer that helped a cloud software company clear their queue. Worth a look?

---

Example 15: Recruiting Tech (Candidate Experience Pain)
Target: VP of Talent or Head of Recruiting
Existential Data Point: Offer acceptance rate < 70%
Data Cocktail: Glassdoor reviews mentioning "slow interview process" + 5+ open recruiter roles + competitive hiring market (AI/ML roles)

Email 1 - PREVIEW
Subject: Offer acceptance in a competitive market
I noticed you're hiring 5 recruiters and competing for AI/ML talent. A few Glassdoor reviews mention a slow interview process. That combination usually means offer acceptance has dropped below target.
When acceptance falls under 70%, every dollar spent on sourcing leaks out the bottom of the funnel. The companies winning candidates have found that speed is the variable that matters most, not comp.

Email 2 - ENGAGE
Subject: How a fast-growing AI company hit 91% offer acceptance
A fast-growing AI company faced brutal competition for AI talent. Same candidate pool, same comp bands, but they were losing offers to faster-moving companies.
They compressed their interview loop from 3 weeks to 5 days. Same rigor, fewer stages. Offer acceptance jumped from 68% to 91%. They stopped losing candidates to competitors who simply moved faster.
Your recruiter hiring and market suggest the same challenge.

Email 3 - ASK
Subject: Interview funnel audit
Happy to map your current interview stages and show where candidates likely drop. Takes 15 minutes and you keep the analysis.
We build the recruiting ops layer that helped a fast-growing AI company compress their loop. Worth a conversation?

---

Example 16: Support Tech (Ticket Resolution Pain)
Target: VP of Customer Support or Head of CX
Existential Data Point: Average resolution time > 24 hours
Data Cocktail: Job posting for "Support Operations Manager" + Zendesk in stack + G2 reviews mentioning slow response times

Email 1 - PREVIEW
Subject: Resolution time and retention
I noticed you're hiring a Support Ops Manager and a few G2 reviews mention response times. That combination usually means resolution time has stretched past where it should be.
When tickets take longer than 24 hours, CSAT drops and churn risk spikes. The companies fixing this have found that most delay isn't agent capacity. It's tickets routed to the wrong queue or missing context on arrival.

Email 2 - ENGAGE
Subject: How a customer communications platform cut resolution time by 60%
A customer communications platform had the same problem. Ticket volume growing, resolution times stretching, CSAT sliding. They tried hiring more agents. Marginal improvement.
They rebuilt their routing logic and auto-populated ticket context before agents saw them. Resolution time dropped from 26 hours to 10. CSAT jumped 18 points. Same team size handled 40% more volume.
Your support hiring and G2 feedback suggest the same pattern.

Email 3 - ASK
Subject: Ticket routing audit
Happy to look at your current queue structure and show where delays likely compound. Takes 15 minutes and you keep the analysis.
We build the support intelligence layer that helped a customer communications platform fix their routing. Worth a look?

---

Example 17: IT Service Management (Incident Response Pain)
Target: VP of IT or Head of Infrastructure
Existential Data Point: Mean time to resolve > 4 hours
Data Cocktail: Job posting for "Site Reliability Engineer" + PagerDuty in stack + status page showing recent incidents

Email 1 - PREVIEW
Subject: Incident resolution at scale
I noticed a few recent incidents on your status page and you're hiring SREs. That combination usually means resolution time has become a problem.
When MTTR stretches past 4 hours, every incident becomes expensive. Revenue impact, customer trust, and engineer burnout compound. The companies resolving faster have found that most time is spent figuring out what's wrong, not fixing it.

Email 2 - ENGAGE
Subject: How a fast-scaling dev tools company cut MTTR from 6 hours to 45 minutes
A fast-scaling dev tools company faced this as they scaled. More services, more dependencies, more incidents. Engineers spent hours triangulating before they could fix. MTTR crept toward 6 hours.
They built an automated correlation layer that pinpointed root cause in minutes instead of hours. MTTR dropped to 45 minutes. On-call burnout dropped. Customer impact per incident fell 80%.
Your incident pattern and SRE hiring suggest the same pressure.

Email 3 - ASK
Subject: Incident pattern analysis
Happy to look at your recent incidents and show where resolution time likely compounds. Takes 15 minutes and you keep the analysis.
We build the observability layer that helped a fast-scaling dev tools company find root cause faster. Worth a conversation?

---

Example 18: Sales Enablement (Rep Ramp Pain)
Target: VP of Sales Enablement or CRO
Existential Data Point: Rep ramp time > 6 months
Data Cocktail: 15+ new AE hires in last quarter + job posting for "Enablement Manager" + Gong or Chorus in stack

Email 1 - PREVIEW
Subject: AE ramp and Q4 pressure
I noticed you hired 15+ AEs last quarter and you're adding an Enablement Manager. That combination usually means ramp time has stretched past where it needs to be.
When reps take longer than 6 months to hit quota, your capacity math breaks. You're paying full OTE for partial productivity. The companies ramping faster have found that content isn't the problem. It's knowing which content when.

Email 2 - ENGAGE
Subject: How a hypergrowth communications company cut rep ramp from 7 months to 3
A hypergrowth communications company faced this during hypergrowth. New reps every week, but time-to-productivity kept stretching. Enablement built more content. Reps got more overwhelmed. Average ramp hit 7 months.
They flipped from content libraries to guided paths. Right content at right deal stage, surfaced automatically. Ramp dropped from 7 months to 3. First-quarter quota attainment jumped from 34% to 71%.
Your hiring pace and enablement focus suggest the same pattern.

Email 3 - ASK
Subject: Ramp path audit
Happy to map your current onboarding flow and show where reps likely get stuck. Takes 15 minutes and you keep the analysis.
We build the enablement layer that helped a hypergrowth communications company accelerate ramp. Worth a look?

---

Example 19: API Platform (Developer Adoption Pain)
Target: VP of Product or Head of Developer Relations
Existential Data Point: API activation rate < 30%
Data Cocktail: Public API with developer docs + job posting for "Developer Advocate" + low GitHub stars relative to funding

Email 1 - PREVIEW
Subject: API signups vs activation
I noticed your API docs are solid but you're hiring a Developer Advocate. That combination usually means signups aren't converting to active integrations.
When activation sits under 30%, your developer funnel leaks. You're generating interest but not usage. The companies fixing this have found that developers don't fail at integration. They fail at first value. Different problem, different fix.

Email 2 - ENGAGE
Subject: How a developer platform company 3x'd API activation
A developer platform company faced this in their early growth. Developers signed up, poked around, and left. Activation sat at 22%. DevRel focused on awareness. Didn't move activation.
They rebuilt onboarding around time-to-first-API-call. Under 5 minutes from signup to working code. Activation jumped from 22% to 68%. The developers who made one call almost always made a thousand.
Your DevRel hiring and doc quality suggest the same gap.

Email 3 - ASK
Subject: Activation path audit
Happy to walk through your API onboarding as a developer and show where friction likely hides. Takes 20 minutes and you keep the analysis.
We build the developer experience layer that helped a developer platform company fix activation. Worth a look?

---

Example 20: Accounting Tech (Close Process Pain)
Target: VP of Finance or Controller
Existential Data Point: Month-end close > 10 days
Data Cocktail: Job posting for "Accounting Manager" + NetSuite or Sage in stack + recent acquisition or entity growth

Email 1 - PREVIEW
Subject: Close time with multiple entities
I noticed you added two entities this year and you're hiring an Accounting Manager. That combination usually means month-end close has stretched past where it should be.
When close takes longer than 10 days, finance operates on stale data. Decisions wait. The companies closing faster have found that the problem isn't people. It's reconciliation across systems that don't talk to each other.

Email 2 - ENGAGE
Subject: How a workforce management company cut close from 15 days to 3
A workforce management company faced this during expansion. More entities, more intercompany transactions, more reconciliation. Close stretched to 15 days. Finance was always looking backward.
They automated intercompany reconciliation and eliminated 80% of manual journal entries. Close dropped from 15 days to 3. Finance shifted from month-end scramble to real-time visibility.
Your entity growth and accounting hiring suggest the same pressure.

Email 3 - ASK
Subject: Close process audit
Happy to map your current close workflow and show where time likely compounds. Takes 20 minutes and you keep the analysis.
We build the accounting automation layer that helped a workforce management company accelerate close. Worth a look?

---

**PART 4: IT MSP (7)**

Example 21: Break-Fix Burnout
Target: Owner or Office Manager at a 50-person professional services firm
Existential Data Point: IT incidents > 10/month with no dedicated IT staff
Data Cocktail: Job posting for "Office Manager" mentioning "tech support responsibilities" + Google reviews mentioning service delays + growing headcount on LinkedIn

Email 1 - PREVIEW
Subject: Tech support falling on the wrong people
I noticed your Office Manager posting mentions tech support as a responsibility. That usually means IT issues are landing on people whose real job is something else.
When a 50-person company hits 10+ tech incidents a month without dedicated IT, productivity bleeds. Your best people spend hours on password resets and printer jams. The companies that fix this find that outsourced IT costs less than the hidden productivity tax.

Email 2 - ENGAGE
Subject: How a 60-person law firm got 15 hours back per week
A law firm your size faced the same problem. Paralegals troubleshooting Outlook. Office manager rebooting the server. Partners frustrated by billable hour leaks.
They moved to managed IT. Response time dropped from hours to minutes. The office manager got 15 hours back per week. Billable recovery improved because attorneys stopped fixing their own tech.
Your job posting and team size suggest the same pattern.

Email 3 - ASK
Subject: Quick IT audit
Happy to run a 20-minute assessment of your current setup and show where time is likely leaking. You keep the report either way.
We handle IT for 30+ firms your size. Worth a conversation?

---

Example 22: Compliance Deadline Pressure
Target: Practice Manager or Owner at a healthcare clinic
Existential Data Point: HIPAA compliance gaps with audit approaching
Data Cocktail: Recent expansion (new location announced) + no IT staff on LinkedIn + healthcare vertical with compliance requirements

Email 1 - PREVIEW
Subject: HIPAA and the new location
Congrats on the new location. Expanding a healthcare practice also means expanding your compliance surface. Most clinics your size don't have dedicated IT to manage HIPAA across multiple sites.
When compliance gaps exist during expansion, audit risk spikes. The practices staying clean have found that compliance isn't a one-time fix. It's monitoring, documentation, and someone accountable for both.

Email 2 - ENGAGE
Subject: How a 4-location clinic passed their HIPAA audit clean
A multi-location clinic faced this last year. Expanding fast, patient data in multiple systems, no IT staff tracking compliance. They were 90 days from an audit with no documentation.
They brought in managed IT focused on healthcare. Passed the audit with zero findings. Got a compliance dashboard that tracks all four locations. The owner stopped losing sleep over breach risk.
Your expansion timing and practice size suggest the same pressure.

Email 3 - ASK
Subject: Compliance gap check
Happy to run a 30-minute HIPAA readiness check and show where gaps likely are. You keep the findings either way.
We manage IT and compliance for 20+ healthcare practices. Worth a look?

---

Example 23: Cybersecurity Wake-Up Call
Target: Owner or CFO at a financial services firm
Existential Data Point: No dedicated security + recent industry breach news
Data Cocktail: SEC/FINRA regulated industry + under 100 employees + no security roles on LinkedIn + recent breach at similar firm in news

Email 1 - PREVIEW
Subject: Security after the recent breach at a similar firm
You probably saw the breach at a 50-person financial firm last month. No dedicated security, client data exposed. Regulatory investigation ongoing.
Firms your size are the primary target now. Big enough to have valuable data, small enough to lack defenses. The firms staying protected have found that basic security hygiene stops 90% of attacks. But someone has to own it.

Email 2 - ENGAGE
Subject: How a 40-person RIA locked down in 30 days
An RIA your size called us after a phishing attempt almost succeeded. No MFA. No email filtering. No endpoint protection. They got lucky.
We implemented a security baseline in 30 days. MFA everywhere, email scanning, endpoint monitoring, and staff training. They passed their SEC cybersecurity review with zero findings. Total cost was less than one compliance violation.
Your regulatory environment and firm size suggest similar exposure.

Email 3 - ASK
Subject: Security gap assessment
Happy to run a 30-minute security review and show where you're most exposed. You keep the findings either way.
We manage security for 25+ financial services firms. Worth a look?

---

Example 24: Remote Work Chaos
Target: Owner or HR Director at a professional services company
Existential Data Point: Hybrid workforce with no unified IT management
Data Cocktail: Job postings mention "remote" or "hybrid" + multiple office locations + no IT staff on LinkedIn

Email 1 - PREVIEW
Subject: IT support across 3 locations and home offices
I noticed your team is spread across multiple locations with hybrid work options. That setup usually means IT support has become inconsistent and slow.
When remote employees wait hours for help, productivity drops and frustration builds. The companies making hybrid work have found that centralized remote management costs less than the lost hours and turnover from poor support.

Email 2 - ENGAGE
Subject: How a 70-person consulting firm fixed remote IT
A consulting firm your size had the same chaos. Some people in-office, some remote, some rotating. IT issues took a day to resolve. New hire setup took a week.
They moved to managed IT with remote monitoring. Support tickets now resolve in under an hour regardless of location. New hires are productive on day one. Employee satisfaction scores jumped.
Your hybrid setup and location spread suggest the same challenge.

Email 3 - ASK
Subject: Remote support audit
Happy to map your current support model and show where remote employees likely struggle. Takes 20 minutes and you keep the analysis.
We manage IT for 30+ hybrid companies. Worth a conversation?

---

Example 25: M&A IT Integration
Target: Owner or COO at a company that recently acquired another business
Existential Data Point: Two separate IT environments post-acquisition
Data Cocktail: Press release about acquisition + different tech stacks visible (different email domains, different tools) + no IT integration role posted

Email 1 - PREVIEW
Subject: IT after the acquisition
Congrats on the acquisition. Combining two companies also means combining two IT environments. Most acquisitions this size don't budget for IT integration.
When systems stay separate, you get duplicate costs, security gaps at the seams, and teams that can't collaborate. The companies capturing acquisition value fast have found that IT integration unlocks everything else.

Email 2 - ENGAGE
Subject: How a merged accounting firm saved $80K year one
Two accounting firms merged last year. Different email systems, different file storage, different security policies. Staff couldn't share files. Clients got confused by two email domains.
We unified them in 60 days. Single email domain, shared files, consistent security. They eliminated $80K in duplicate software and reduced client confusion to zero.
Your acquisition timing and visible tech differences suggest the same opportunity.

Email 3 - ASK
Subject: Integration roadmap
Happy to map both IT environments and show where quick wins likely are. Takes 30 minutes and you keep the roadmap.
We've handled IT integration for 10+ acquisitions. Worth a look?

---

Example 26: IT Person Dependency
Target: Owner or Operations Director at a company with one IT person
Existential Data Point: Single IT employee with no backup or documentation
Data Cocktail: LinkedIn shows exactly one IT person + company size 50-150 employees + IT person tenure 5+ years

Email 1 - PREVIEW
Subject: Your IT single point of failure
I noticed your IT setup depends on one person who's been there 7 years. That's a lot of knowledge in one head.
When your only IT person takes vacation, gets sick, or leaves, everything they know walks out with them. The companies protecting themselves have found that documentation plus backup support costs far less than the chaos of sudden departure.

Email 2 - ENGAGE
Subject: What happened when the IT guy quit with 2 weeks notice
A 100-person company called us in a panic. Their IT person of 8 years quit. No documentation. Passwords in his head. Server configurations unknown.
We stabilized them in a week and documented everything. Now they have managed IT plus their new internal hire. The hire focuses on projects. We handle support and backup. No single point of failure.
Your setup and IT tenure suggest similar risk.

Email 3 - ASK
Subject: Continuity check
Happy to assess your current documentation and backup coverage. Takes 20 minutes and you keep the findings.
We provide backup support for 20+ companies with internal IT. Worth a conversation?

---

Example 27: Insurance/Compliance Pressure
Target: Owner or CFO at a company with cyber insurance requirements
Existential Data Point: Cyber insurance renewal with new security requirements
Data Cocktail: Industry with cyber insurance mandates (legal, healthcare, financial) + company size requiring coverage + no security roles on LinkedIn

Email 1 - PREVIEW
Subject: Cyber insurance renewal requirements
I saw that cyber insurance renewals are requiring MFA, endpoint protection, and backup verification this year. Most companies your size don't have dedicated IT to prove compliance.
When you can't document security controls, premiums spike or coverage gets denied. The companies renewing smoothly have found that implementing the requirements costs less than the premium increase for not having them.

Email 2 - ENGAGE
Subject: How a law firm saved $15K on cyber insurance
A 40-person law firm faced a 60% premium increase at renewal. They couldn't prove MFA was enforced or that backups were tested. Carrier was ready to walk.
We implemented the required controls in 3 weeks and documented everything. Premium increase dropped to 8%. Total project cost was less than one year of the avoided premium hike.
Your industry and company size suggest similar renewal pressure.

Email 3 - ASK
Subject: Insurance readiness check
Happy to review your current security posture against typical carrier requirements. Takes 20 minutes and you keep the gap analysis.
We help 30+ companies meet cyber insurance requirements. Worth a look?

---

**PART 5: ADDITIONAL VERTICALS (8)**

Example 28: EdTech (Student Engagement Pain)
Target: VP of Product or Head of Learning at an EdTech company
Existential Data Point: Student engagement drop > 40% inactive after 14 days
Data Cocktail: App store reviews mentioning "boring" or "stopped using" + job posting for "Learning Experience Designer" + high download volume but low DAU

Email 1 - PREVIEW
Subject: Downloads vs daily active learners
I noticed your app has strong download numbers but several reviews mention engagement dropping off after the first week. You're also hiring a Learning Experience Designer. That combination usually means completion rates are below target.
When 40%+ of students go inactive within 14 days, your acquisition spend doesn't convert to outcomes. The companies fixing this have found that engagement dies at predictable moments, not randomly.

Email 2 - ENGAGE
Subject: How an edtech platform kept learners past day 14
An edtech platform faced this at scale. Millions of downloads, but most users quit within two weeks. They tried more content. Didn't help. Tried gamification. Marginal improvement.
They mapped the exact moments learners dropped and rebuilt those transitions. Day 14 retention jumped from 23% to 51%. Same content, completely different pacing. Completion rates followed.
Your review patterns and hiring suggest the same engagement cliff.

Email 3 - ASK
Subject: Engagement drop-off analysis
Happy to map your current learner journey and show where students likely disengage. Takes 20 minutes and you keep the analysis.
We build the learning analytics layer that helped an edtech platform find their retention levers. Worth a look?

---

Example 29: PropTech / Real Estate (Vacancy Rate Pain)
Target: VP of Operations or Head of Leasing at a property management company
Existential Data Point: Vacancy rate > 10%
Data Cocktail: Listings sitting 30+ days on Zillow/Apartments.com + job posting for "Leasing Specialist" + portfolio expansion announced

Email 1 - PREVIEW
Subject: Vacancy rate during expansion
I noticed several of your listings have been active for 30+ days and you're hiring Leasing Specialists while expanding the portfolio. That combination usually means vacancy has crept past target.
When vacancy crosses 10%, debt service gets tight and NOI suffers. The operators controlling vacancy have found that most extended vacancies stem from pricing lag, not demand. The market moved and pricing didn't.

Email 2 - ENGAGE
Subject: How a large property management company cut vacancy from 12% to 6%
A large property management company faced this across 200+ properties. Market rents shifting weekly, but pricing updated monthly. Vacancies stretched. Revenue leaked.
They built dynamic pricing that adjusted to real-time market signals. Vacancy dropped from 12% to 6% in one quarter. Revenue per unit increased even as rents flexed. Same properties, completely different yield.
Your listing age and portfolio growth suggest the same opportunity.

Email 3 - ASK
Subject: Pricing gap analysis
Happy to pull your current listings against market comps and show where pricing likely lags. Takes 20 minutes and you keep the analysis.
We build the revenue optimization layer that helped a large property management company close their vacancy gap. Worth a look?

---

Example 30: Construction Tech (Project Schedule Variance Pain)
Target: VP of Operations or Head of Project Management at a GC or specialty contractor
Existential Data Point: Schedule variance > 15% behind
Data Cocktail: Job posting for "Project Controls Manager" + multiple active projects on website + industry known for delays

Email 1 - PREVIEW
Subject: Schedule variance and liquidated damages
I noticed you're hiring a Project Controls Manager and have 8 active projects listed. That combination usually means schedule variance has become a financial problem.
When projects run 15%+ behind, liquidated damages kick in and profit disappears. The contractors staying on schedule have found that most delay comes from coordination gaps, not labor or materials. The information moved slower than the work.

Email 2 - ENGAGE
Subject: How a national general contractor cut schedule overruns by 40%
A national general contractor faced this on complex projects. Subs waiting on information. RFIs taking days. Schedule slipping while everyone pointed fingers.
They built a coordination layer that surfaced blockers before they caused delays. Schedule variance dropped 40%. Liquidated damages nearly eliminated. PM time shifted from firefighting to prevention.
Your project volume and controls hiring suggest the same pressure.

Email 3 - ASK
Subject: Schedule risk assessment
Happy to look at your current project mix and show where coordination delays likely hide. Takes 20 minutes and you keep the analysis.
We build the project intelligence layer that helped a national general contractor stay on schedule. Worth a look?

---

Example 31: Construction Tech (Change Order Rate Pain)
Target: CFO or VP of Preconstruction at a general contractor
Existential Data Point: Change order rate > 10% of contract value
Data Cocktail: Job posting for "Estimator" or "Preconstruction Manager" + large project announcements + competitive bid market

Email 1 - PREVIEW
Subject: Change orders and margin erosion
I noticed you're hiring estimators and recently won several competitive bids. That combination usually means change order rates have crept past comfortable levels.
When changes exceed 10% of contract value, margin erodes and client relationships strain. The contractors protecting margin have found that most changes stem from scope gaps caught too late, not unforeseen conditions.

Email 2 - ENGAGE
Subject: How a large design-build contractor cut change orders by 60%
A large design-build contractor faced this on complex projects. Scope gaps discovered during construction. Change orders stacking up. Margins shrinking.
They rebuilt their preconstruction review process to catch gaps before groundbreak. Change order rate dropped from 14% to 5%. Client satisfaction improved. Rebid rates on negotiated work increased because owners trusted the number.
Your estimating hiring and bid volume suggest the same opportunity.

Email 3 - ASK
Subject: Scope gap analysis
Happy to look at your recent project data and show where change orders likely originate. Takes 20 minutes and you keep the analysis.
We build the preconstruction layer that helped a large design-build contractor protect their margins. Worth a conversation?

---

Example 32: AgTech (Yield Variance Pain)
Target: VP of Operations or Head of Agronomy at a large farm operation or ag cooperative
Existential Data Point: Yield variance > 15% below forecast
Data Cocktail: Weather events in region + job posting for "Precision Ag Specialist" + commodity price pressure in news

Email 1 - PREVIEW
Subject: Yield variance and input costs
I noticed you're hiring a Precision Ag Specialist and your region had significant weather variance this season. That combination usually means yield came in below forecast.
When actual yield misses by 15%+, input costs don't adjust and margins compress. The operations hitting targets have found that most variance comes from input timing, not input volume. Same spend, different results.

Email 2 - ENGAGE
Subject: How a 50K-acre operation closed their yield gap
A large corn operation faced this two seasons ago. Inputs applied on schedule, but yield lagged forecast by 18%. Weather blamed, but neighbors had better results.
They added variable-rate application based on real-time field conditions. Yield variance dropped from 18% to 4%. Input costs actually decreased. Same acres, completely different precision.
Your hiring and regional conditions suggest the same opportunity.

Email 3 - ASK
Subject: Yield variance analysis
Happy to look at your field data and show where variance likely concentrates. Takes 20 minutes and you keep the analysis.
We build the precision ag layer that helped close that yield gap. Worth a look?

---

Example 33: Hospitality / Restaurant (Labor Cost Pain)
Target: VP of Operations or Director of Restaurant Operations at a multi-unit restaurant group
Existential Data Point: Labor cost > 35% of revenue
Data Cocktail: Job postings for multiple GM roles + locations on delivery platforms + minimum wage increases in region

Email 1 - PREVIEW
Subject: Labor cost after minimum wage increase
I noticed you're hiring GMs across several locations and your region just saw a minimum wage bump. That combination usually means labor cost has crossed the threshold that makes unit economics work.
When labor exceeds 35% of revenue, you're choosing between service cuts and margin loss. The operators holding the line have found that scheduling precision matters more than headcount reduction.

Email 2 - ENGAGE
Subject: How a multi-location restaurant chain held labor at 28% through wage increases
A multi-location restaurant chain faced this across 200+ locations. Wages rising, but cutting staff hurt service and sales. Labor crept toward 36%.
They built demand-based scheduling that matched staffing to 15-minute sales forecasts. Labor dropped to 28% without service cuts. Throughput actually improved because staffing matched demand peaks.
Your location count and wage environment suggest the same pressure.

Email 3 - ASK
Subject: Labor optimization audit
Happy to look at your scheduling patterns and show where labor likely misaligns with demand. Takes 20 minutes and you keep the analysis.
We build the workforce layer that helped a multi-location restaurant chain hit their labor targets. Worth a conversation?

---

Example 34: Nonprofit / Association (Donor Retention Pain)
Target: VP of Development or Director of Fundraising at a nonprofit
Existential Data Point: Donor retention rate < 45%
Data Cocktail: Job posting for "Development Associate" + annual campaign visible + GuideStar profile showing flat or declining revenue

Email 1 - PREVIEW
Subject: Donor retention and fundraising efficiency
I noticed you're hiring a Development Associate and your annual campaign is active. That combination usually means donor retention has dropped below sustainable levels.
When retention falls under 45%, you're replacing nearly half your donor base every year. Acquisition can't outpace churn. The organizations stabilizing revenue have found that retention fails at predictable moments, not randomly.

Email 2 - ENGAGE
Subject: How a fast-growing nonprofit pushed retention to 68%
A fast-growing nonprofit faced this during rapid growth. Acquiring donors faster, but retention dropping. Net revenue flat despite bigger campaigns.
They mapped the donor journey and found three moments where lapse risk spiked. Rebuilt touchpoints at those moments. Retention jumped from 41% to 68%. Acquisition spend finally compounded instead of just replacing churn.
Your hiring and revenue patterns suggest the same opportunity.

Email 3 - ASK
Subject: Retention risk analysis
Happy to map your donor journey and show where lapse risk likely concentrates. Takes 20 minutes and you keep the analysis.
We build the donor intelligence layer that helped a fast-growing nonprofit find their retention moments. Worth a conversation?

---

Example 35: Government / GovTech (Citizen Service Backlog Pain)
Target: CIO or Director of Digital Services at a city or county government
Existential Data Point: Service request backlog > 30 days average response
Data Cocktail: 311 data showing long resolution times + job posting for "Constituent Services Manager" + public complaints in local news

Email 1 - PREVIEW
Subject: Service request backlog and constituent trust
I noticed your 311 data shows average resolution times over 30 days and you're hiring for Constituent Services. That combination usually means the backlog has become a political problem.
When residents wait a month for responses, trust erodes and complaints escalate to elected officials. The agencies clearing backlogs have found that most delay comes from routing, not capacity.

Email 2 - ENGAGE
Subject: How a major city government cut service response from 35 days to 5
A major city government faced this with 500+ daily requests. Backlog growing, residents frustrated, council members getting calls. They tried adding staff. Backlog kept growing.
They rebuilt their intake and routing system to auto-categorize and prioritize. Average response dropped from 35 days to 5. Same staff handled 3x the volume. Constituent satisfaction scores doubled.
Your resolution times and hiring suggest the same opportunity.

Email 3 - ASK
Subject: Backlog analysis
Happy to look at your current request flow and show where delays likely compound. Takes 20 minutes and you keep the analysis.
We build the constituent services layer that helped a major city government clear their backlog. Worth a look?

---

**PART 6: ADDITIONAL HORIZONTAL SaaS (5)**

Example 36: HRIS / Payroll (Payroll Error Pain)
Target: VP of People or Head of HR at a scaling company
Existential Data Point: Payroll error rate > 2%
Data Cocktail: Rapid headcount growth on LinkedIn + job posting for "Payroll Specialist" + multiple states/countries in job locations

Email 1 - PREVIEW
Subject: Payroll accuracy across 12 states
I noticed you've grown to 200+ employees across 12 states and you're hiring a Payroll Specialist. That combination usually means payroll errors have become a recurring problem.
When error rates cross 2%, trust erodes and compliance risk grows. The companies running clean payroll have found that most errors stem from multi-state tax complexity, not data entry mistakes.

Email 2 - ENGAGE
Subject: How a website platform company eliminated payroll errors during hypergrowth
A website platform company faced this scaling from 50 to 300 employees across 20 states. Errors every cycle. HR spending days on corrections. Employees losing trust.
They consolidated onto a system that handled multi-state automatically. Error rate dropped from 4% to near zero. HR got two days back per cycle. Employee satisfaction with payroll hit 98%.
Your growth rate and geographic spread suggest the same complexity.

Email 3 - ASK
Subject: Payroll complexity audit
Happy to map your current state/entity structure and show where errors likely originate. Takes 15 minutes and you keep the analysis.
We handle payroll for 50+ multi-state companies. Worth a look?

---

Example 37: Contract Lifecycle Management (Contract Visibility Pain)
Target: General Counsel or VP of Legal Ops
Existential Data Point: No centralized contract repository with search
Data Cocktail: Job posting for "Contracts Manager" + M&A activity or rapid growth + legal team size < 5

Email 1 - PREVIEW
Subject: Contract visibility and renewal risk
I noticed you're hiring a Contracts Manager and your legal team is lean for your company size. That combination usually means contracts live in too many places to track.
When you can't search contracts, renewals get missed and obligations get forgotten. The legal teams with visibility have found that centralization takes weeks, not months. The hard part is getting started.

Email 2 - ENGAGE
Subject: How a 500-person company found $400K in missed renewals
A company your size had contracts in email, cloud storage, and a shared drive. Legal couldn't answer basic questions without digging. Auto-renewals triggered they didn't want.
They centralized in 4 weeks. Found $400K in renewals to cancel or renegotiate. Legal now answers contract questions in minutes. Renewal surprises eliminated.
Your team size and growth rate suggest the same gap.

Email 3 - ASK
Subject: Contract inventory assessment
Happy to estimate how many contracts you likely have and where they probably live. Takes 15 minutes and you keep the analysis.
We help legal teams get visibility in weeks, not months. Worth a conversation?

---

Example 38: Knowledge Management (Knowledge Findability Pain)
Target: VP of Operations or Head of Enablement
Existential Data Point: Average search-to-find time > 10 minutes
Data Cocktail: Multiple knowledge tools in stack (Notion, Confluence, Google Drive, SharePoint) + remote workforce + job posting mentioning "documentation"

Email 1 - PREVIEW
Subject: Finding information across 4 systems
I noticed your team uses multiple knowledge tools based on job postings. That combination usually means finding information takes longer than it should.
When search-to-find exceeds 10 minutes, employees give up and interrupt colleagues instead. The companies with findable knowledge have consolidated, not organized. Less tools, better search.

Email 2 - ENGAGE
Subject: How a DevOps platform company cut search time from 12 minutes to 30 seconds
A DevOps platform company had the same sprawl. Docs in five places. Employees spending 12 minutes hunting for answers. Productivity leaking hourly across 1,500 people.
They unified search across all sources. Didn't move the docs, just made them findable. Search time dropped to 30 seconds. Interruptions dropped 60%. Onboarding accelerated because new hires could self-serve.
Your tool count and remote setup suggest the same friction.

Email 3 - ASK
Subject: Knowledge fragmentation audit
Happy to map your current knowledge sources and show where findability likely breaks. Takes 15 minutes and you keep the analysis.
We unify search for 20+ distributed companies. Worth a look?

---

Example 39: Business Intelligence (Dashboard Sprawl Pain)
Target: VP of Data or Head of Analytics
Existential Data Point: 50+ dashboards with no clear ownership
Data Cocktail: Tableau or Looker in stack + job posting for "Analytics Engineer" + data team size growing

Email 1 - PREVIEW
Subject: Dashboard count and data trust
I noticed you're scaling your analytics team and running a BI platform across the organization. That combination usually means dashboard sprawl has become a governance problem.
When you have 50+ dashboards with unclear ownership, conflicting numbers erode trust. The teams with credible data have shifted from dashboard building to metric governance.

Email 2 - ENGAGE
Subject: How an e-commerce platform cut dashboards from 400 to 80
An e-commerce platform faced this at scale. Everyone built dashboards. Nobody retired them. Leadership got different numbers depending on who they asked. Trust in data collapsed.
They implemented a metrics layer with clear ownership. Dashboard count dropped from 400 to 80. But more importantly, the 80 were trusted. Decisions accelerated because no one debated the numbers.
Your tool and team growth suggest the same sprawl.

Email 3 - ASK
Subject: Dashboard governance audit
Happy to estimate your current dashboard count and show where conflicting metrics likely exist. Takes 15 minutes and you keep the analysis.
We help data teams build trusted metrics layers. Worth a conversation?

---

Example 40: Integration Platform (Integration Maintenance Pain)
Target: VP of Engineering or Head of Platform
Existential Data Point: 20+ point-to-point integrations with no middleware
Data Cocktail: Large app count visible (Okta, SSO provider) + job posting for "Integration Engineer" + data sync issues mentioned in reviews

Email 1 - PREVIEW
Subject: Integration maintenance and engineering time
I noticed your SSO shows 40+ connected apps and you're hiring an Integration Engineer. That combination usually means integration maintenance has become a significant time sink.
When you have 20+ point-to-point integrations, every app change breaks something else. Engineering spends time fixing syncs instead of building product. The teams escaping this have added a layer in the middle.

Email 2 - ENGAGE
Subject: How a productivity software company cut integration maintenance by 80%
A productivity software company faced this scaling their app ecosystem. 50+ integrations, each built custom. App updates broke syncs weekly. Engineering spent 20% of time on maintenance.
They added an integration layer that abstracted the connections. Maintenance time dropped 80%. New integrations went from weeks to days. Engineering shifted back to product work.
Your app count and hiring suggest the same friction.

Email 3 - ASK
Subject: Integration architecture audit
Happy to map your current integration landscape and show where maintenance likely concentrates. Takes 20 minutes and you keep the analysis.
We help engineering teams escape integration debt. Worth a look?

---

**SECTION B: PARTIAL-SIGNAL PVP EXAMPLES**

When Auggie has incomplete, ambiguous, or unconfirmed data, use these patterns. Key principles:
- Name the ambiguity explicitly rather than picking one interpretation
- Offer value conditionally: "If X is true, here's something useful"
- Give permission to ignore: reduces pressure, increases trust
- Position insights as benchmarks, not diagnoses
- Use when: only 1 signal available, signal older than 60 days, signal has multiple interpretations, only industry/stage data without company-specific confirmation

Example 41: Single Signal, Multiple Interpretations
Signal quality: Low-Confidence -- Single job posting
What Auggie found: Job posting for "Data Engineer" -- no other signals
What's missing: Supporting context (pipeline issues, data product plans, infrastructure scaling)
Hedging pattern: Names multiple interpretations, offers value for one, gives permission to ignore for others

Email 1 - PREVIEW
Subject: Data engineering hire
I noticed you're hiring a Data Engineer. That role gets added for different reasons: scaling infrastructure, fixing pipeline debt, or preparing for a data product push.
If it's pipeline debt causing the pain, I've seen where most companies your size find the worst bottlenecks. The pattern is surprisingly consistent. If it's one of the other reasons, feel free to ignore me entirely.

Email 2 - ENGAGE
Subject: Where pipeline debt usually hides
A company in a similar situation hired a Data Engineer to fix reliability issues. Their pipelines ran, but late. Data arrived stale. Dashboards refreshed hours behind decisions.
They audited their pipeline graph and found 80% of failures traced to three ingestion points. Fixed those first. Freshness went from hours to minutes. The new hire focused on building forward instead of firefighting.
That's a common pattern when the hire is debt-driven. Might not match your situation at all.

Email 3 - ASK
Subject: Pipeline diagnostic
I have a 15-minute diagnostic that shows where pipeline bottlenecks typically cluster for companies your size. It's yours regardless of whether we ever talk again.
We build the data reliability layer that helped that company clear their debt. If pipeline is the reason for the hire, might be worth a look.

---

Example 42: Signal Present, Severity Unknown
Signal quality: Low-Confidence -- Unconfirmed severity
What Auggie found: G2 reviews mention "steep learning curve" -- no other confirmation
What's missing: Activation rate data, volume of affected users, CS team response
Hedging pattern: Acknowledges inability to gauge severity from outside, offers benchmark value either way

Email 1 - PREVIEW
Subject: Onboarding feedback
I saw a few G2 reviews mention a learning curve with your product. Hard to tell from the outside whether that's a handful of vocal users or something affecting activation rates more broadly.
If it's the latter and your CS team is working on it, I've mapped where similar products see the biggest drop-off moments. The pattern is consistent enough to be a useful benchmark even if your situation is different.

Email 2 - ENGAGE
Subject: Where learning curves usually break activation
A company in a similar situation had the same G2 feedback. They assumed it was a small vocal group. When they instrumented onboarding, they found 60% of new users stalled at the same three screens.
They simplified those screens without changing the product's power. Activation jumped 35%. The G2 reviews shifted from "steep learning curve" to "powerful but easy to start." Same product, different first experience.
That might not match your scale at all. But if it does, the fix was smaller than they expected.

Email 3 - ASK
Subject: Onboarding benchmark
I have a drop-off benchmark showing where similar products lose users during onboarding. Happy to share. Useful as a comparison point even if your activation is healthy.
We build the onboarding analytics layer that helped that company find their stall points. If the learning curve feedback is a real pattern, worth a conversation.

---

Example 43: Timing-Based Hedge
Signal quality: Low-Confidence -- Pain may not have materialized yet
What Auggie found: Series B announcement, expanding to enterprise segment
What's missing: Confirmation that security questionnaires or procurement friction have started
Hedging pattern: Acknowledges it might be too early, offers value tied to a specific future trigger

Email 1 - PREVIEW
Subject: Enterprise motion timing
Congrats on the Series B. I saw you're moving upmarket into enterprise.
That shift usually surfaces security questionnaire pain about 6-9 months in, when the first big deals hit procurement. Might be too early to matter for you. But if you're starting to see SOC 2 questions come up in deals, the companies who prepare early avoid a scramble later.

Email 2 - ENGAGE
Subject: What the first enterprise deal usually reveals
A company in a similar situation closed their Series B and started chasing enterprise. First two deals sailed through. Third one hit procurement. Security questionnaire with 200 questions. No SOC 2. Deal stalled for 4 months.
They fast-tracked certification and built a security review package. Next 10 enterprise deals closed 60% faster through procurement. The investment paid back on deal three.
If you haven't hit that wall yet, you probably will. Timing is the only question.

Email 3 - ASK
Subject: Enterprise readiness timeline
I have a readiness timeline showing what enterprise buyers typically ask for and when. Happy to send it over. Useful for planning even if procurement friction hasn't started yet.
We help companies prepare for enterprise security requirements before deals stall. If SOC 2 questions are starting to surface, worth a look.

---

Example 44: Industry Pressure Without Company Confirmation
Signal quality: Low-Confidence -- Industry trend only, no company-specific signal
What Auggie found: Company is in healthcare IT, no specific pain signals
What's missing: Any company-specific indicator of compliance pressure, audit burden, or security review friction
Hedging pattern: Leads with industry context, explicitly states uncertainty about company-specific relevance

Email 1 - PREVIEW
Subject: Healthcare compliance pressure
I work with a lot of healthcare IT companies. The compliance landscape has gotten significantly more complex this year. New state privacy laws. Updated HIPAA enforcement.
No idea if that's creating pressure for your team specifically. But if audits or customer security reviews have gotten more time-consuming, the companies cutting prep time have found a few repeatable shortcuts.

Email 2 - ENGAGE
Subject: How healthcare IT companies are handling the new compliance load
A healthcare IT company with a growing customer base found their compliance prep doubling year over year. New state laws meant new requirements for every customer audit. The team was spending more time on compliance than product.
They built a reusable evidence library that mapped to multiple frameworks simultaneously. Prep time dropped by half. Customer security reviews went from weeks to days. Same team handled 3x the audit volume.
That might be completely irrelevant to your situation. But if compliance prep has grown, the pattern is worth knowing.

Email 3 - ASK
Subject: Compliance checklist
I have a checklist covering the newest healthcare compliance requirements that's helped others cut prep time in half. Yours if it's useful. No strings attached.
We build the compliance automation layer that helped that company scale their audit response. If reviews have gotten more time-consuming, might be worth a conversation.

---

Example 45: Role Hire Without Context
Signal quality: Low-Confidence -- Leadership hire with ambiguous intent
What Auggie found: Hired VP of Customer Success (LinkedIn) -- no other signals
What's missing: NRR data, churn indicators, expansion metrics, or team maturity signals
Hedging pattern: Names three possible interpretations, offers value for one, explicitly opts out of the others

Email 1 - PREVIEW
Subject: New CS leadership
I saw you recently brought on a VP of Customer Success. That hire usually means one of three things: NRR needs attention, the team has scaled past founder-led CS, or you're building out a more sophisticated expansion motion.
If it's the NRR situation, I know where similar companies find the biggest retention leaks. If it's one of the others, I'm probably not useful right now.

Email 2 - ENGAGE
Subject: Where NRR leaks usually hide
A company in a similar situation brought on a CS leader to fix retention. Churn looked manageable on the surface, but NRR told a different story. Downgrades were quietly eating expansion revenue.
They mapped every account to health signals and found that churn risk spiked at two predictable moments: month 3 and month 9. Intervening at those moments pushed NRR from 95% to 112%. Same customer base, completely different trajectory.
If NRR isn't the driver behind the hire, this probably doesn't apply. But if it is, the pattern is remarkably consistent.

Email 3 - ASK
Subject: Retention diagnostic
I have a 20-minute diagnostic that shows where retention leaks typically cluster by company stage. It's yours to keep regardless of whether we talk further.
We build the customer intelligence layer that helped that company find their NRR levers. If retention is the priority, worth a look.

---

Example 46: Competitor Signal Only
Signal quality: Low-Confidence -- External market event, no company-specific reaction
What Auggie found: Competitor just raised Series C, likely creating pressure
What's missing: Any indication the company is changing strategy, accelerating spend, or feeling competitive pressure
Hedging pattern: Frames as market context, explicitly acknowledges it may not be changing anything for the company

Email 1 - PREVIEW
Subject: Market timing
I noticed your competitor just raised a big round. That usually creates some urgency for others in the space, either to accelerate roadmap or tighten up GTM efficiency.
No idea if that's changing anything for you. But if you're looking at CAC or sales cycle as a response, the companies that respond well focus on efficiency, not just speed.

Email 2 - ENGAGE
Subject: How companies respond to competitor funding
A company in a similar situation saw their main competitor raise a large round. The instinct was to spend faster. Instead, they audited their GTM efficiency and found their CAC was 40% higher than it needed to be.
They tightened targeting and shortened their sales cycle by two weeks. Growth actually accelerated while spend stayed flat. When the competitor burned through their raise, they were still standing with better unit economics.
That might not be your playbook at all. But if competitive pressure is driving any GTM conversations, the efficiency-first approach has a strong track record.

Email 3 - ASK
Subject: GTM benchmark data
I have benchmark data on CAC and sales cycle for companies in your space. Yours if useful. Good context regardless of competitive dynamics.
We help companies build efficient GTM motions. If you're evaluating any changes in response to market shifts, might be worth a conversation.

---

Example 47: Partial Funnel Visibility
Signal quality: Low-Confidence -- Conflicting public signals
What Auggie found: High traffic (SimilarWeb) but low app store ratings with friction themes
What's missing: Actual conversion data, activation rates, whether ratings reflect current or legacy experience
Hedging pattern: Names the ambiguity between traffic and ratings, offers framework rather than diagnosis

Email 1 - PREVIEW
Subject: Traffic vs. activation
Your web traffic looks strong, but I noticed your app store ratings have some friction themes in recent reviews. Hard to know from the outside if that's a conversion issue or just a vocal minority.
If there's a gap between traffic and activated users you're trying to close, I've mapped where similar products find the biggest drop-off. The pattern is consistent enough to be a useful framework.

Email 2 - ENGAGE
Subject: Closing the traffic-to-activation gap
A company in a similar situation had strong acquisition but soft activation. App reviews flagged friction, but the team wasn't sure if it was widespread or a few loud voices. Turns out it was both: a real issue amplified by vocal users.
They instrumented the first-session flow and found one screen where 40% of new users bounced. A single UX change recovered half of them. Ratings improved as a side effect. The vocal minority was just the visible tip.
That may not match your situation. But if traffic and activation feel misaligned, the diagnostic approach is straightforward.

Email 3 - ASK
Subject: Activation framework
I have a framework showing where products with strong traffic typically lose users before activation. Happy to share. Useful as a benchmark even if your conversion is healthy.
We build the product analytics layer that helped that company find their drop-off point. If there's a gap you're working on, worth a look.

---

Example 48: Stale Signal
Signal quality: Low-Confidence -- Signal older than 60 days
What Auggie found: Job posting from 3 months ago for "Revenue Operations Manager" -- may be filled
What's missing: Confirmation role is still open, whether the hire has ramped, current state of pipeline visibility
Hedging pattern: Acknowledges the signal may be outdated, offers value that's useful even if the problem is being solved

Email 1 - PREVIEW
Subject: Rev ops from earlier this year
I saw you were hiring a Revenue Operations Manager a few months back. Might be fully ramped by now, in which case ignore this.
But if pipeline visibility or forecast accuracy is still a work in progress, I've seen where similar companies find the biggest gaps. The pattern is consistent enough to be a useful benchmark even if things are improving.

Email 2 - ENGAGE
Subject: What the first 90 days of rev ops usually reveals
A company in a similar situation hired a Rev Ops Manager and expected quick wins. Ninety days in, they had better data but the same forecast accuracy. The problem wasn't visibility. It was that reps weren't updating stages consistently.
They built a system that inferred stage from activity instead of relying on manual updates. Forecast accuracy jumped from 60% to 85% in one quarter. The Rev Ops hire shifted from data cleanup to strategic analysis.
If your hire is past this phase, you probably don't need this. But if forecast accuracy is still climbing, the pattern might help.

Email 3 - ASK
Subject: Rev ops benchmark
I have a 15-minute diagnostic showing where pipeline visibility gaps typically persist even after a rev ops hire. Useful as a benchmark even if things are trending well.
We build the revenue intelligence layer that helped that company fix their forecast. If accuracy is still a work in progress, worth a conversation.

---

Example 49: Inferred Pain From Funding Stage
Signal quality: Low-Confidence -- Stage-based inference only
What Auggie found: Series A announced, 30 employees on LinkedIn
What's missing: Any specific operational pain signal -- just stage and size
Hedging pattern: Frames as stage-typical patterns, explicitly invites self-selection on which pain resonates

Email 1 - PREVIEW
Subject: Post-Series A ops
Congrats on the A. At your stage, 30ish people with fresh capital and pressure to scale, ops usually starts breaking in predictable ways. Hiring outpaces onboarding. Tools multiply without integration. Reporting becomes a scramble.
No idea which of those is loudest for you right now. But if any of them resonate, I've got a checklist of what typically needs attention first at your stage.

Email 2 - ENGAGE
Subject: What usually breaks at 30 people
A post-Series A company with about 30 people found that everything worked until it didn't. Onboarding was tribal knowledge. Five tools did overlapping things. The CEO built reports manually every board meeting.
They prioritized three fixes: documented onboarding, consolidated tools, and automated board reporting. Took 6 weeks. The CEO got a day back per month. New hires ramped in half the time. The ops foundation held through doubling headcount.
Every company at this stage has a different version of this story. The specifics vary, but the pattern doesn't.

Email 3 - ASK
Subject: Post-Series A checklist
I have a checklist of what typically needs attention first at your stage, built from working with dozens of companies post-A. Happy to send it over, yours regardless.
We help companies build the ops foundation that scales past 30 people. If any of those pain points resonate, worth a conversation.

---

Example 50: Public Metric Without Context
Signal quality: Low-Confidence -- Visible metric without trend data
What Auggie found: NPS score visible on website (42) -- no trend data
What's missing: Historical trend, segment breakdown, whether the score is improving or declining
Hedging pattern: Acknowledges the number without judging it, offers context that's valuable regardless of direction

Email 1 - PREVIEW
Subject: NPS context
I saw your NPS is posted at 42. Solid number in most contexts, but impossible to know from the outside whether it's trending up, flat, or down from where it was.
If you're working on moving it and looking for where similar companies find the most leverage, I've got a breakdown of what typically drives the biggest swings. The drivers are surprisingly consistent across company size.

Email 2 - ENGAGE
Subject: What typically moves NPS the most
A company in a similar situation had their NPS at 40 and couldn't figure out what would move it. They surveyed detractors. Got vague feedback. Tried fixing everything. Nothing moved.
They segmented NPS by customer journey stage and found that scores cratered at one specific moment: the transition from onboarding to steady-state. Fixing that handoff moved NPS from 40 to 58 in two quarters. One moment, not ten initiatives.
If your 42 is trending up, you might already know your lever. If it's flat or down, segmentation usually reveals it.

Email 3 - ASK
Subject: NPS driver breakdown
I have a breakdown of what drives NPS movement for companies at your stage, segmented by journey moment. Yours if useful, no strings attached.
We build the customer intelligence layer that helped that company find their NPS lever. If you're actively working on the score, worth a conversation.

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

**SUBJECT LINE RULES**

Write 3 subject line options for the sequence. Emails 2 and 3 will appear as replies in the same thread.

Subject lines must be PRIORITY-BASED — name something from the prospect's world, not yours. Use language that speaks to:
- **Priorities**: Specific initiatives your buyer cares about (stated publicly or common among their peers)
- **Current solutions & problems**: How they're making progress — their tools, people, process, and associated problems
- **Aspirations**: Outcomes they hope to achieve, their desired future state

Keep it simple, short, and boring. Think casual internal note, not sales email.

Rules:
- MAX 4 words. Shorter is better. 1-2 words is ideal.
- All lowercase. No title case. No sentence case.
- No pitching, no value props, no benefits, no "how to" framing
- No questions, no exclamation marks, no numbers/stats, no buzzwords
- NEVER use the word "AI" in a subject line
- Reference something specific from the prospect's world: a project, initiative, industry term, competitor name, internal challenge, or metric
- Each of the 3 options must take a genuinely different angle — different hook entirely, not a rephrase

Good examples (priority-based, from the prospect's world):
- "WCUS achievement gaps" (references their specific challenge by name)
- "Italy hiring issue" (references a specific finding from research)
- "participant dropouts" (names their problem, not your solution)
- "learning gaps"
- "welders"
- "metro push"
- "warehouse automation"
- "q4 pipeline"
- "denial rates"

Bad examples (DO NOT write subject lines like these):
- "Fix WCUS classroom instruction with AI" (pitchy, includes solution, says "AI")
- "Streamline HR & International Hiring" (pitchy, describes your value prop)
- "Reduce study build times by 37%" (pitchy, uses numbers/stats)
- "How a mid-market company cut costs by 40%" (social proof framing)
- "Quick funnel audit" (pitching your product)
- "Following up on database scaling" (too long, generic)

NOTE: The PVP examples in this prompt have older-style subject lines. IGNORE those example subject lines. Follow THESE rules instead.

---

**BEFORE YOU SUBMIT**

Count the words in each email body. If any email exceeds its limit, rewrite shorter.
Count the words in each subject line. If any exceeds 4 words, rewrite shorter.

---

Present your final output in this format:

<email_series>
<subject1>[subject line option 1]</subject1>
<subject2>[subject line option 2 — different angle]</subject2>
<subject3>[subject line option 3 — different angle]</subject3>

<email1>
[body]
</email1>

<email2>
[body]
</email2>

<email3>
[body]
</email3>
</email_series>
{low_confidence_closing}"""

        # Strip Section A examples for low-score prospects so the model
        # can't pattern-match off full-confidence examples.
        if opportunity_score is not None and opportunity_score < 50:
            # Find the section intro and Section A, replace with partial-signal header
            section_a_start = "**ADDITIONAL PVP EXAMPLES**"
            section_b_start = "**SECTION B: PARTIAL-SIGNAL PVP EXAMPLES**"
            start_idx = prompt.find(section_a_start)
            end_idx = prompt.find(section_b_start)
            if start_idx != -1 and end_idx != -1:
                replacement = (
                    "**PARTIAL-SIGNAL PVP EXAMPLES**\n\n"
                    "The following 10 examples show how to write valuable sequences "
                    "when data is incomplete.\n\n---\n\n"
                )
                prompt = prompt[:start_idx] + replacement + prompt[end_idx:]

        return prompt

    def _parse_emails(self, response: str) -> tuple[list[dict], list[str]]:
        """Parse the email series from the response.

        Returns:
            Tuple of (emails list, subject_options list).
        """
        emails = []

        # Extract subject line options (new format: subject1/subject2/subject3)
        subject_options = []
        for i in range(1, 4):
            m = re.search(rf"<subject{i}>(.*?)</subject{i}>", response, re.DOTALL)
            if m:
                subject_options.append(m.group(1).strip())

        # Fall back to legacy single <subject> tag
        if not subject_options:
            legacy = re.search(r"<subject>(.*?)</subject>", response, re.DOTALL)
            subject_options = [legacy.group(1).strip()] if legacy else ["Following up"]

        # Use the first subject option as default for all emails
        subject = subject_options[0]

        # Extract each email block
        for i in range(1, 4):
            pattern = f"<email{i}>(.*?)</email{i}>"
            match = re.search(pattern, response, re.DOTALL)

            if match:
                body = match.group(1).strip()

                emails.append({
                    "email_number": i,
                    "subject": subject,
                    "body": body
                })

        return emails, subject_options

    async def generate_email_sequence(
        self,
        document: ResearchDocument,
        product_context: str,
        product_type: str = "saas",
        retrieved_materials: str = "",
        seller_company: str = "",
        problems_solved: str = "",
    ) -> tuple[list[dict], list[str]]:
        """Generate a 3-email sequence from a research document.

        Returns:
            Tuple of (emails list, subject_options list).
        """

        # Build the report from research
        report = self._build_report(document, product_context, retrieved_materials,
                                     seller_company=seller_company, problems_solved=problems_solved)

        # Build the full prompt
        prompt = self._build_prompt(report, document.opportunity_score, product_type=product_type)

        # Call writing model
        message = await self.client.chat.completions.create(
            model=self.settings.writing_model,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )

        response = message.choices[0].message.content or ""

        # Parse the emails
        emails, subject_options = self._parse_emails(response)

        return emails, subject_options

    def format_emails_markdown(self, emails: list[dict]) -> str:
        """Format emails as markdown for display."""
        sections = ["# Email Sequence\n"]

        for email in emails:
            sections.append(f"## Email {email['email_number']}")
            sections.append(f"**Subject:** {email['subject']}\n")
            sections.append(email['body'])
            sections.append("\n---\n")

        return "\n".join(sections)
