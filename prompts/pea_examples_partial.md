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