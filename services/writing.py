"""writing.py - AI-powered outreach generation."""

import logging
import re
import time
from openai import AsyncOpenAI
from typing import Optional
from models import ResearchDocument
from config import get_settings
from services.pea_selector import load_prompt_sections

logger = logging.getLogger(__name__)

WORD_LIMITS = {1: 75, 2: 100, 3: 60}


class SequenceValidationError(Exception):
    """Raised when a generated sequence fails validation after all repair attempts."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class WritingService:
    """Service for generating outreach emails from research documents."""

    def __init__(self):
        self.settings = get_settings()
        self.client = AsyncOpenAI(
            api_key=self.settings.openrouter_api_key,
            base_url="https://openrouter.ai/api/v1",
            timeout=60.0,
        )

    def _build_report(self, document: ResearchDocument, product_context: str, retrieved_materials: str = "",
                       seller_company: str = "", problems_solved: str = "", persona_context: str = "",
                       custom_signals: str = "") -> str:
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

        if document.before_scenario:
            sections.append("## Before Scenario (Problems → Consequences → Current Attempts)")
            sections.append(document.before_scenario)
            sections.append("")

        if document.pvp_seed:
            sections.append("## PVP Seed (Key Insight for Outreach)")
            sections.append(document.pvp_seed)
            sections.append("")

        if document.projects_initiatives:
            sections.append("## Current Projects & Initiatives")
            sections.append(document.projects_initiatives)
            sections.append("")

        # Tech stack intentionally excluded from outreach context —
        # leads the model to open with technology observations instead of
        # business problems, which reads as robotic to prospects.

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

        if document.recommended_contacts:
            sections.append("## Recommended Contacts")
            sections.append(document.recommended_contacts)
            sections.append("")

        if persona_context:
            sections.append("## Target Contact")
            sections.append(persona_context)
            sections.append("")

        sections.append("## Our Product (What We're Selling)")
        if seller_company:
            sections.append(f"**Company:** {seller_company}")
        sections.append(product_context)

        if problems_solved:
            sections.append("")
            sections.append("## Specific Problems We Solve")
            sections.append(f"Align email angles to these problems when the research shows a match: {problems_solved}")

        if custom_signals:
            sections.append("")
            sections.append("## Custom Signals to Emphasize")
            sections.append(f"If the research mentions any of these, use them as email hooks: {custom_signals}")

        if retrieved_materials:
            sections.append("")
            sections.append("## Sales Materials (Case Studies, Battle Cards, Proof Points)")
            sections.append("Use these to reference specific results, metrics, and customer stories in your emails.")
            sections.append(retrieved_materials)

        return "\n".join(sections)

    def _build_system_prompt(self, opportunity_score: Optional[int] = None,
                              product_type: str = "saas",
                              seller_product_category: str = "") -> str:
        """Build the system message with framework, rules, and examples.

        Loads from externalized prompt files when available. Falls back to
        inline prompt if any file fails to load.
        """
        use_selector = getattr(self.settings, "pea_selector_enabled", False)
        sections = load_prompt_sections(
            opportunity_score=opportunity_score,
            product_type=product_type,
            seller_product_category=seller_product_category,
            use_selector=use_selector,
        )

        # Fail-soft: if core rules loaded successfully, compose from files
        if sections["rules_core"]:
            parts = [sections["rules_core"]]
            if sections["subject_rules"]:
                parts.append(sections["subject_rules"])
            if sections["examples"]:
                parts.append(sections["examples"])
            return "\n\n---\n\n".join(parts)

        # Fallback: use inline prompt if files failed to load
        logger.warning("Prompt files unavailable, using inline fallback")
        return self._build_system_prompt_inline(opportunity_score)

    def _build_system_prompt_inline(self, opportunity_score: Optional[int] = None) -> str:
        """Inline fallback prompt — used when prompt files fail to load."""

        prompt = """You are an expert at crafting Personalized Value Propositions (PVPs) for B2B sales outreach.

**Your job:** Use research to demonstrate you understand their problem, then explain why you can help. The research is proof of understanding, not the point of the email.

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

Subject lines must be PRIORITY-BASED -- name something from the prospect's world, not yours. Use language that speaks to:
- **Priorities**: Specific initiatives your buyer cares about (stated publicly or common among their peers)
- **Current solutions & problems**: How they're making progress -- their tools, people, process, and associated problems
- **Aspirations**: Outcomes they hope to achieve, their desired future state

Keep it simple, short, and boring. Think casual internal note, not sales email.

Rules:
- MAX 4 words. Shorter is better. 1-2 words is ideal.
- All lowercase. No title case. No sentence case.
- No pitching, no value props, no benefits, no "how to" framing
- No questions, no exclamation marks, no numbers/stats, no buzzwords
- NEVER use the word "AI" in a subject line
- Reference something specific from the prospect's world: a project, initiative, industry term, competitor name, internal challenge, or metric
- Each of the 3 options must take a genuinely different angle -- different hook entirely, not a rephrase

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

**ADDITIONAL PVP EXAMPLES**

The following 13 examples show the PEA framework in action. They are split into two sections:

**Section A (Examples 1-6): Full-Confidence PVPs** -- Multiple confirming signals triangulate to a specific pain. Use these as patterns for standard outreach.

**Section B (Examples 41-47): Partial-Signal PVPs** -- Only one signal available, signal is ambiguous, stale, or lacks company-specific confirmation. These demonstrate how to write valuable sequences when data is incomplete.

---

**SECTION A: FULL-CONFIDENCE PVP EXAMPLES**

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

Example 2: Product / PLG (Free-to-Paid Conversion Pain)
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

Example 3: MSP Break-Fix Burnout
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

Example 4: Construction Tech (Project Schedule Variance Pain)
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

Example 5: Government / GovTech (Citizen Service Backlog Pain)
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

Example 6: Dev Tooling / API Platform (Integration Velocity Pain)
Target: VP of Engineering or Head of Platform at a mid-market SaaS company
Existential Data Point: API integration backlog > 6 months
Data Cocktail: Job posting for "Integrations Engineer" + partner page listing 30+ integrations + changelog showing slow release cadence

Email 1 - PREVIEW
Subject: Integration backlog and partner pressure
I noticed you have 30+ integrations listed and you're hiring an Integrations Engineer. That usually means the backlog of partner requests has outgrown what the current team can ship.
When integration velocity drops, partners lose patience and customers build brittle workarounds. The platforms shipping integrations fastest have found that most of the delay is boilerplate, not business logic.

Email 2 - ENGAGE
Subject: How a B2B platform cut integration build time by 70%
A B2B platform had the same bottleneck. Forty partner integrations queued. Each one took 6-8 weeks. Engineering kept getting pulled off product work to build connectors.
They moved the repeatable parts of each integration to a managed runtime. Build time dropped from 6 weeks to 9 days. The integrations engineer focused on edge cases instead of auth flows and retry logic. Partner satisfaction scores jumped.
Your integration count and hiring suggest the same pressure.

Email 3 - ASK
Subject: Integration audit
Happy to look at your current integration architecture and show where build time likely clusters. Takes 15 minutes and you keep the analysis.
We handle the infrastructure layer that helped that platform ship integrations faster. Worth a look?

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

Example 42: Timing-Based Hedge
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

Example 43: Industry Pressure Without Company Confirmation
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

Example 44: Role Hire Without Context
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

Example 45: Stale Signal
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

Example 46: Inferred Pain From Funding Stage
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

Example 47: Dev Tooling Adoption Without Usage Data
Signal quality: Low-Confidence -- Stack presence only, no usage or pain signals
What Auggie found: Company uses a serverless provider (visible in job posts or tech profile) -- no other signals
What's missing: Scale of usage, cold start complaints, cost pressure, migration intent
Hedging pattern: Leads with a stage-typical pattern, offers benchmark, gives permission to opt out

Email 1 - PREVIEW
Subject: Serverless at scale
I saw your team is running on serverless. At a certain point most teams hit a predictable set of tradeoffs: cold starts slow down user-facing flows, costs get harder to predict, and debugging distributed functions becomes its own job.
No idea if any of that applies to you yet. But if one of those has started showing up, the pattern for what to fix first is surprisingly consistent.

Email 2 - ENGAGE
Subject: What usually breaks first on serverless
A company in a similar situation was happy with serverless until traffic grew. Cold starts added 2-3 seconds to API responses. Costs spiked unpredictably with each launch. The team spent more time tracing failures across functions than building features.
They kept serverless for background jobs but moved latency-sensitive paths to a managed compute layer. API response times dropped 80%. Monthly cloud bill became predictable. Engineering time shifted back to product.
That might not match where you are at all. Plenty of teams run serverless without hitting these walls.

Email 3 - ASK
Subject: Compute cost benchmark
I have a benchmark showing where serverless costs typically inflect relative to request volume. Yours regardless of whether it's relevant today.
We handle the compute layer that helped that company solve their latency and cost problems. If any of those tradeoffs are showing up, worth a conversation.

---

**WORD LIMITS (MANDATORY)**

Count words before submitting each email. If over the limit, rewrite shorter. These are requirements, not guidelines.

- Email 1: 75 words max
- Email 2: 100 words max
- Email 3: 60 words max

Present your output in EXACTLY this format (no other headers or commentary):

Subject 1: [subject line option 1]
Subject 2: [subject line option 2 -- different angle]
Subject 3: [subject line option 3 -- different angle]

Email 1:
[body]

Email 2:
[body]

Email 3:
[body]"""

        # Strip Section A examples for low-score prospects so the model
        # can't pattern-match off full-confidence examples.
        if opportunity_score is not None and opportunity_score < 50:
            section_a_start = "**ADDITIONAL PVP EXAMPLES**"
            section_b_start = "**SECTION B: PARTIAL-SIGNAL PVP EXAMPLES**"
            start_idx = prompt.find(section_a_start)
            end_idx = prompt.find(section_b_start)
            if start_idx != -1 and end_idx != -1:
                replacement = (
                    "**PARTIAL-SIGNAL PVP EXAMPLES**\n\n"
                    "The following 7 examples show how to write valuable sequences "
                    "when data is incomplete.\n\n---\n\n"
                )
                prompt = prompt[:start_idx] + replacement + prompt[end_idx:]

        return prompt

    def _build_user_prompt(self, report: str, opportunity_score: Optional[int] = None,
                            product_type: str = "saas", has_persona: bool = False) -> str:
        """Build the user message with prospect-specific context and task."""

        parts = ["Generate a 3-email PVP sequence for the following prospect."]

        if opportunity_score is not None and opportunity_score < 50:
            parts.append(f"""**LOW-CONFIDENCE RESEARCH -- PARTIAL-SIGNAL MODE**

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

Use the partial-signal examples as your primary models for this sequence.""")

        if product_type == "msp":
            parts.append(
                "**PROFESSIONAL SERVICES / CONSULTANCY FRAMING -- APPLY TO ALL EMAILS:**\n"
                "\n"
                "- Lead with operational complexity and the burden of managing specialist functions alongside core business. The prospect runs a company where the seller's domain (IT, data, analytics, compliance) is a distraction from their actual work.\n"
                "- Frame around reliability, compliance, data-driven decisions, and freeing up leadership attention -- not digital transformation or innovation.\n"
                "- The prospect may not be a tech buyer -- avoid unnecessary jargon. Frame everything in business terms: uptime, risk, cost predictability, reporting clarity, compliance peace of mind.\n"
                "- Reference pain they feel daily: systems going down, reports that take days to assemble, compliance audit anxiety, decisions made on gut feel instead of data, implementation backlogs growing.\n"
                "- Position professional services as removing a burden, not adding a capability. Examples: managed IT handling infrastructure so the owner doesn't have to, data consultancies turning messy spreadsheets into dashboards, implementation partners clearing project backlogs."
            )

        if has_persona:
            parts.append(
                "**PERSONA-TARGETED OUTREACH:**\n"
                "\n"
                "The report includes a Target Contact section with a specific person's LinkedIn profile data. "
                "Personalize emails for this individual:\n"
                "- Use their first name naturally in EVERY email body -- Email 1, Email 2, AND Email 3 (not in subject lines)\n"
                "- Email 2 (the proof email): bridge back to the prospect by name when connecting the case study to their situation\n"
                "- Reference their specific role and responsibilities when connecting to pain points\n"
                "- Frame insights through the lens of what matters to someone in their position\n"
                "- Do NOT mention that you saw their LinkedIn profile or researched them personally\n"
                "- Do NOT reference their career history, skills section, or about section directly\n"
                "- The personalization should feel like you understand their role, not like you stalked their profile"
            )

        parts.append(f"<report>\n{report}\n</report>")

        return "\n\n".join(parts)

    def _parse_emails(self, response: str) -> tuple[list[dict], list[str]]:
        """Parse the email series from freeform model output.

        Handles multiple formats the model might use:
        - "Subject N: text" or numbered lists or <subjectN> XML tags
        - "Email N:" headers, "**Email N**" bold headers, "## Email N" markdown, <emailN> XML tags

        Returns:
            Tuple of (emails list, subject_options list).
        """
        emails = []

        # --- Subject parsing ---
        subject_options = []

        # "Subject N: text"
        subject_matches = re.findall(r"[Ss]ubject\s*\d\s*:\s*(.+)", response)
        if subject_matches:
            subject_options = [s.strip().strip("`\"'") for s in subject_matches[:3]]

        # <subject1>text</subject1> XML tags
        if not subject_options:
            for i in range(1, 4):
                m = re.search(rf"<subject{i}>(.*?)</subject{i}>", response, re.DOTALL)
                if m:
                    subject_options.append(m.group(1).strip())

        # Numbered list near "subject" context: 1. `text`
        if not subject_options:
            subject_block = re.search(r"[Ss]ubject.*?:(.*?)(?:\n\n|---|\*\*Email|Email \d)", response, re.DOTALL)
            if subject_block:
                numbered = re.findall(r"^\s*\d+\.\s*[`\"']?([^`\"'\n]+)[`\"']?\s*$", subject_block.group(1), re.MULTILINE)
                subject_options = [s.strip() for s in numbered[:3]]

        if not subject_options:
            subject_options = ["Following up"]

        subject = subject_options[0]

        # --- Email body parsing ---

        # Split on any "Email N" header variant
        parts = re.split(r"(?:^|\n)\s*(?:\*\*|##?\s*)?Email\s*(\d)[^\n]*\n", response)
        if len(parts) >= 3:
            for j in range(1, len(parts) - 1, 2):
                num = int(parts[j])
                body = parts[j + 1].strip()
                body = re.sub(r"^\s*\*?\*?Body:?\*?\*?\s*\n?", "", body)
                body = re.sub(r"\n?---\s*$", "", body).strip()
                body = body.replace("**", "")
                emails.append({
                    "email_number": num,
                    "subject": subject,
                    "body": body
                })

        # Fallback: <email1>text</email1> XML tags
        if not emails:
            for i in range(1, 4):
                m = re.search(rf"<email{i}>(.*?)</email{i}>", response, re.DOTALL)
                if m:
                    body = m.group(1).strip().replace("**", "")
                    emails.append({
                        "email_number": i,
                        "subject": subject,
                        "body": body
                    })

        if not emails:
            logger.warning("Failed to parse emails from model response. First 500 chars: %s", response[:500])

        return emails, subject_options

    def _validate_sequence(self, emails: list[dict], subject_options: list[str]) -> tuple[bool, str]:
        """Validate a parsed email sequence meets structural requirements.

        Word limits are NOT checked here — they are enforced separately by the
        shorten pipeline after validation, so over-limit emails get a chance to
        be shortened rather than triggering an immediate failure.

        Returns (is_valid, error_message).
        """
        if len(emails) != 3:
            return False, f"Expected 3 emails, got {len(emails)}"

        expected_numbers = {1, 2, 3}
        actual_numbers = {e["email_number"] for e in emails}
        if actual_numbers != expected_numbers:
            return False, f"Email numbers must be 1,2,3 — got {sorted(actual_numbers)}"

        for email in emails:
            if not email.get("subject", "").strip():
                return False, f"Email {email['email_number']} has empty subject"
            if not email.get("body", "").strip():
                return False, f"Email {email['email_number']} has empty body"

        if not subject_options:
            return False, "No subject options provided"

        return True, ""

    async def _repair_sequence_output(self, raw_response: str) -> str:
        """Ask the model to repair a malformed sequence into the expected format."""
        repair_prompt = (
            "The following email sequence output is malformed. "
            "Rewrite it into EXACTLY this format with no other text:\n\n"
            "Subject 1: [subject line option 1]\n"
            "Subject 2: [subject line option 2]\n"
            "Subject 3: [subject line option 3]\n\n"
            "Email 1:\n[body]\n\n"
            "Email 2:\n[body]\n\n"
            "Email 3:\n[body]\n\n"
            "Keep the same content, just fix the formatting. "
            "Each email must have a non-empty body. "
            "Output ONLY the formatted sequence.\n\n"
            f"--- MALFORMED OUTPUT ---\n{raw_response}"
        )
        message = await self.client.chat.completions.create(
            model=self.settings.writing_model,
            max_tokens=2000,
            messages=[{"role": "user", "content": repair_prompt}],
        )
        result = message.choices[0].message.content or ""
        # Clean up emdashes and bold markers
        result = (
            result
            .replace("\u2014", " - ")
            .replace("\u2013", " - ")
            .replace("\u2015", " - ")
            .replace("\u2012", " - ")
        )
        result = re.sub(r"\*+(.+?)\*+", r"\1", result)
        return result.strip()

    def _over_limit_emails(self, emails: list[dict]) -> list[dict]:
        """Return emails that exceed their word limit."""
        over = []
        for email in emails:
            limit = WORD_LIMITS.get(email["email_number"], 100)
            count = len(email["body"].split())
            if count > limit:
                over.append({**email, "word_count": count, "limit": limit})
        return over

    def _trim_to_word_limit(self, body: str, limit: int) -> str:
        """Deterministically trim text to a hard word cap."""
        words = body.split()
        if len(words) <= limit:
            return body.strip()

        # Prefer sentence-preserving trim first.
        sentences = re.split(r"(?<=[.!?])\s+", body.strip())
        kept: list[str] = []
        kept_words = 0
        for sentence in sentences:
            sentence_words = sentence.split()
            if not sentence_words:
                continue
            if kept_words + len(sentence_words) > limit:
                break
            kept.append(sentence.strip())
            kept_words += len(sentence_words)

        if kept and kept_words > 0:
            return " ".join(kept).strip()

        # Fallback: strict token trim.
        return " ".join(words[:limit]).strip()

    async def _shorten_email(self, email: dict) -> str:
        """Ask the model to rewrite an over-limit email shorter."""
        prompt = (
            f"Rewrite this email to be UNDER {email['limit']} words. "
            f"It is currently {email['word_count']} words.\n"
            "Keep the same message, tone, and structure. Just cut it down.\n"
            "Output ONLY the rewritten email body. No headers, labels, or commentary.\n\n"
            f"{email['body']}"
        )
        message = await self.client.chat.completions.create(
            model=self.settings.writing_model,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        result = message.choices[0].message.content or ""
        result = (
            result
            .replace("\u2014", " - ")
            .replace("\u2013", " - ")
            .replace("\u2015", " - ")
            .replace("\u2012", " - ")
        )
        result = re.sub(r"\*+(.+?)\*+", r"\1", result)
        return result.strip()

    async def generate_email_sequence(
        self,
        document: ResearchDocument,
        product_context: str,
        product_type: str = "saas",
        retrieved_materials: str = "",
        seller_company: str = "",
        problems_solved: str = "",
        persona_context: str = "",
        custom_signals: str = "",
    ) -> tuple[list[dict], list[str]]:
        """Generate a 3-email sequence from a research document.

        Returns:
            Tuple of (emails list, subject_options list).
        """

        start_time = time.monotonic()
        doc_id = getattr(document, "id", None)
        telemetry = {
            "event_type": "email_generation",
            "doc_id": doc_id,
            "parse_success": False,
            "validation_pass": False,
            "repair_attempted": False,
            "repair_success": False,
            "prompt_mode": "unknown",
            "word_limit_pass": False,
        }

        # Build the report from research
        report = self._build_report(document, product_context, retrieved_materials,
                                     seller_company=seller_company, problems_solved=problems_solved,
                                     persona_context=persona_context, custom_signals=custom_signals)

        # Build system and user prompts
        system_prompt = self._build_system_prompt(
            document.opportunity_score,
            product_type=product_type,
            seller_product_category=product_context,
        )
        user_prompt = self._build_user_prompt(report, document.opportunity_score, product_type=product_type,
                                              has_persona=bool(persona_context))

        # Call writing model
        message = await self.client.chat.completions.create(
            model=self.settings.writing_model,
            max_tokens=2000,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )

        response = message.choices[0].message.content or ""

        # Strip emdashes — model ignores the "no emdashes" style rule occasionally
        response = (
            response
            .replace("\u2014", " - ")   # em dash
            .replace("\u2013", " - ")   # en dash
            .replace("\u2015", " - ")   # horizontal bar
            .replace("\u2012", " - ")   # figure dash
        )

        # Strip markdown bold/italic markers — emails are plain text
        response = re.sub(r"\*+(.+?)\*+", r"\1", response)

        # Track prompt mode
        score = document.opportunity_score if document.opportunity_score is not None else 50
        telemetry["prompt_mode"] = "partial" if score < 50 else "full"

        # Parse the emails
        emails, subject_options = self._parse_emails(response)
        telemetry["parse_success"] = len(emails) > 0

        # Validate -> repair once -> validate
        valid, error_msg = self._validate_sequence(emails, subject_options)
        telemetry["validation_pass"] = valid
        repair_attempted = False
        repair_success = False

        if not valid:
            # Attempt one repair pass
            repair_attempted = True
            telemetry["repair_attempted"] = True
            try:
                repaired_response = await self._repair_sequence_output(response)
                emails, subject_options = self._parse_emails(repaired_response)
                valid, error_msg = self._validate_sequence(emails, subject_options)
                repair_success = valid
                telemetry["repair_success"] = repair_success
                telemetry["validation_pass"] = valid
            except Exception:
                logger.warning("Repair pass failed", exc_info=True)

            if not valid:
                telemetry["latency_ms"] = int((time.monotonic() - start_time) * 1000)
                logger.info("Email generation failed", extra=telemetry)
                raise SequenceValidationError(
                    code="sequence_validation_failed" if not repair_attempted else "sequence_repair_failed",
                    message=error_msg or "Generated sequence failed validation after repair",
                )

        # Enforce word limits — retry over-limit emails once
        over = self._over_limit_emails(emails)
        if over:
            for ov in over:
                # Try model-based shortening twice before deterministic hard trim.
                for _attempt in range(2):
                    try:
                        shortened = await self._shorten_email(ov)
                        for email in emails:
                            if email["email_number"] == ov["email_number"]:
                                email["body"] = shortened
                                break

                        refreshed = self._over_limit_emails([email for email in emails if email["email_number"] == ov["email_number"]])
                        if not refreshed:
                            break
                        ov = refreshed[0]
                    except Exception:
                        logger.warning("Failed to shorten email %d (was %d words, limit %d)",
                                       ov["email_number"], ov["word_count"], ov["limit"])

                # Last-resort hard cap to avoid user-facing dead-end.
                for email in emails:
                    if email["email_number"] == ov["email_number"]:
                        email["body"] = self._trim_to_word_limit(email["body"], ov["limit"])
                        break

            # Re-validate after shortening
            still_over = self._over_limit_emails(emails)
            if still_over:
                over_details = ", ".join(
                    f"Email {o['email_number']}: {o['word_count']}/{o['limit']}"
                    for o in still_over
                )
                telemetry["word_limit_pass"] = False
                telemetry["latency_ms"] = int((time.monotonic() - start_time) * 1000)
                logger.info("Email generation failed word limits", extra=telemetry)
                raise SequenceValidationError(
                    code="sequence_validation_failed",
                    message=f"Emails still over word limit after shortening: {over_details}",
                )

        telemetry["word_limit_pass"] = True
        telemetry["latency_ms"] = int((time.monotonic() - start_time) * 1000)
        logger.info("Email generation completed", extra=telemetry)

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
