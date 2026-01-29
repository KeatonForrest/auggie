# Auggie Product Roadmap

## Vision: Intelligence Orchestration

**Auggie is the intelligence layer between list building and outreach.**

We don't build lists. We don't send emails. We answer: *"Which accounts have active pain, and what do I say?"*

### Philosophy: Target Pain, Not Personas

Traditional prospecting: "I sell to VPs of Engineering at Series B SaaS companies"

Auggie approach: "I sell to companies with database scaling pain - the title doesn't matter, the problem does"

### The Workflow

```
INGEST → ANALYZE → ENRICH → WRITE → EXECUTE

500 accounts (ingest)
    → 87 high-pain (analyze)
        → 87 contacts enriched (enrich)
            → 87 sequences written (write)
                → 87 sent (execute)
```

Each step filters. Don't pay to enrich or write for accounts that aren't ready.

### Integration Points

**Ingest from:**
- Ocean.io (lookalikes)
- Clay (tables)
- Apollo (saved lists)
- HubSpot (companies)
- Salesforce (accounts)
- CSV upload

**Enrich via:**
- LeadMagic (contacts)
- Apollo (contacts)
- Clearbit (firmographics)

**Execute to:**
- Instantly
- Outreach
- Salesloft
- HubSpot sequences
- Salesforce

---

## Current Status: v2 LIVE IN PRODUCTION + PUBLIC API COMPLETE
- Core research generation working (Claude Opus 4)
- Materials upload & RAG working
- Writing workflow (PVP email sequences) working
- Consumption pricing (1 free, $10 for 10 credits) working
- Admin accounts (unlimited usage for internal users)
- Public API with async jobs, webhooks, rate limiting, sequence generation
- Live at https://auggie.tools

---

## Phase 1: Production Launch
**Status:** COMPLETE

- [x] Core research generation
- [x] Materials upload (PDF, DOCX, PPTX)
- [x] RAG retrieval into research
- [x] Tech stack detection (B2B + B2C)
- [x] Job board scraping (Greenhouse, Lever, Workday, Ashby, etc.)
- [x] User auth (Google OAuth)
- [x] Stripe billing (Free tier + Pro $9.99/mo)
- [x] Simplified onboarding
- [x] Materials prompt modal

**To deploy:**
1. Merge v2 → main
2. Add env vars to production (Neon, R2, OpenAI)
3. Set MATERIALS_ENABLED=true

---

## Phase 2: Contact Enrichment
**Status:** DISABLED (evaluating providers, code in place)

Built LeadMagic integration (role-finder + email-finder) but disabled after testing showed stale/inaccurate contact data (wrong titles, people who left companies, incorrect role matches).

### What's Built (disabled, code in place)
- `services/leadmagic.py` — role-finder and email-finder API client
- `POST /v1/enrich` API endpoint (separate from research)
- `enriched_contacts` DB table
- UI button + display (commented out in document.html)
- Fractional credit support ($0.50 per enrichment)

### Next Steps
- [ ] Evaluate alternative providers: Apollo, RocketReach, Clearbit, PeopleDataLabs
- [ ] Key criteria: data freshness, title accuracy, email deliverability rates
- [ ] Re-enable once a provider meets quality bar
- [ ] Consider multi-provider fallback strategy

---

## Phase 3: Writing Workflow
**Status:** COMPLETE

Add AI-powered outreach generation after research is created.

### Features
- [x] "Write Outreach" button on research document
- [x] Template types:
  - 3-Email Sequence (initial, follow-up, break-up)
- [x] Uses research context + materials + contacts
- [x] Regenerate, copy functionality

### Database
```sql
CREATE TABLE outreach_drafts (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(id),
    document_id BIGINT REFERENCES documents(id),
    template_type TEXT,
    content TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### Files to Create/Modify
- [ ] services/writing.py - Outreach generation service
- [ ] templates/document.html - Add "Write Outreach" UI
- [ ] main.py - Add /outreach endpoints
- [ ] database.py - Add outreach table

---

## Phase 4: Microsoft OAuth
**Status:** COMPLETE

Add Microsoft sign-in for MSP customers using Azure/M365.

### Why
- MSPs live in Microsoft ecosystem (Azure AD, M365, Intune)
- Google OAuth is friction for Microsoft-first organizations
- Opens new customer segment without enterprise SSO complexity

### Features
- [x] Microsoft OAuth provider (alongside Google)
- [x] "Sign in with Microsoft" button on landing page
- [x] Support for personal Microsoft accounts + work/school accounts
- [x] Store microsoft_id in users table (similar to google_id)

### Files Modified
- [x] config.py - Add MICROSOFT_CLIENT_ID, MICROSOFT_CLIENT_SECRET
- [x] auth.py - Register Microsoft OAuth provider, add /auth/microsoft routes
- [x] database.py - Add microsoft_id column, update create_user/get_user functions
- [x] templates/landing.html - Add Microsoft sign-in button

### Azure Portal Setup
1. Go to Azure Portal → App registrations → New registration
2. Name: "Auggie"
3. Supported account types: "Accounts in any organizational directory and personal Microsoft accounts"
4. Redirect URI: https://auggie.tools/auth/microsoft/callback
5. Copy Application (client) ID → MICROSOFT_CLIENT_ID
6. Create client secret → MICROSOFT_CLIENT_SECRET

### Environment Variables
```
MICROSOFT_CLIENT_ID=your_app_id
MICROSOFT_CLIENT_SECRET=your_secret
```

---

## Phase 5: Public API
**Status:** COMPLETE
**PRD:** [PRD_API.md](./PRD_API.md)

The API is the foundation for enterprise. Without it, no Clay integration, no bulk workflows, no "intelligence layer" positioning.

### What's Built
- [x] API key generation + management (bcrypt hashed, sk_live_ prefix)
- [x] `POST /v1/research` - Async research (returns job_id, HTTP 202)
- [x] `GET /v1/research/{job_id}` - Poll for job status + full results
- [x] `GET /v1/research` - List user's recent jobs
- [x] `POST /v1/research/{id}/sequence` - Generate 3-email PVP sequence
- [x] `POST /v1/enrich` - Contact enrichment (disabled, see Phase 2)
- [x] `GET /v1/ping` - Health check
- [x] Opportunity scoring (Pain 40%, Fit 35%, Timing 25%)
- [x] SSRF protection on all research endpoints
- [x] Credit deduction (cents-based fractional credits) with upfront reservation + refund on failure
- [x] Rate limiting (in-memory sliding window per API key)
- [x] Webhook registration (`POST /v1/webhooks/register`, `GET /v1/webhooks`, `DELETE /v1/webhooks`)
- [x] Webhook delivery with HMAC-SHA256 signing on job completion
- [x] Stale job cleanup on app startup (marks processing jobs >10min as failed)
- [x] Dashboard: API key management

### Key API Outputs

**Basic ($1.00/credit):**

| Endpoint | Returns |
|----------|---------|
| `/v1/research` | Research document, talking points |
| `/v1/research/{id}/sequence` | 3-email sequence (BYOC) |

**Full ($1.50/credit):**

| Endpoint | Returns |
|----------|---------|
| `/v1/research` | Opportunity score (pain + fit + timing), research, contact (LeadMagic), talking points |
| `/v1/research/{id}/sequence` | 3-email sequence personalized to enriched contact |
| `/v1/lists/{id}/accounts` | All accounts sorted by opportunity score |

### Success Criteria
- 10 API customers in 90 days
- 1,000 API calls/month
- < 1% error rate
- P95 latency < 45 seconds

---

## Phase 6: Bulk Lists + Docs + SDK
**Status:** COMPLETE

Build bulk processing and developer documentation.

### Bulk Research API
- [x] `POST /v1/research/bulk` - Bulk research (up to 100 URLs, bounded concurrency)
- [x] `GET /v1/research/bulk/{id}` - Poll bulk job progress + items
- [x] `GET /v1/research/bulk` - List recent bulk jobs
- [x] Background job processing (async with semaphore, 5 concurrent)
- [x] Credit reservation + refund on failure
- [x] Rate limiting (2 bulk requests / 60s)
- [x] Webhook notification on bulk completion

### Lists
- [x] `POST /v1/lists` - Create persistent list from domains (with optional immediate analysis)
- [x] `POST /v1/lists/{id}/analyze` - Trigger analysis on pending accounts
- [x] `GET /v1/lists/{id}` - Get accounts with pain scores, filtering/sorting
- [x] `GET /v1/lists` - List recent lists
- [x] `DELETE /v1/lists/{id}` - Delete list and accounts

### Docs + SDK
- [x] API documentation page (`/docs`)
- [x] Python SDK (`sdk/auggie/`)
- [x] Clay integration guide (`/guides/clay-problem-signal-prospecting`)
- [x] Dashboard: API key usage stats

---

## Phase 7: Clay Marketplace
**Status:** Planned
**Timeline:** 30-60 day onboarding process (runs in background)

Become an official enrichment provider in Clay's marketplace. This is the primary distribution channel for API adoption.

### Why Clay First
- 150+ enrichment providers, but none do problem-signal scoring
- Clay users are exactly our ICP: RevOps teams building outbound workflows
- Marketplace listing = free distribution to Clay's entire customer base
- Co-marketing starts after integration is live

### Steps
- [x] Build API (Phase 5 prerequisite)
- [x] Build Clay-compatible synchronous enrichment endpoint
- [x] Add 24-hour caching to avoid duplicate costs
- [x] Update docs and Clay guide with sync endpoint
- [x] Create /integrations/clay landing page
- [ ] Contact Clay Data Partnerships Team
- [ ] Join shared Slack channel with Clay engineer
- [ ] Test integration end-to-end with Clay team
- [ ] Publish to Clay marketplace
- [ ] Create Clay workflow template: "Problem-Signal Prospecting"

### Auggie as a Clay Column
```
Clay Table:
┌──────────┬─────────────┬───────────────┬─────────────┬──────────────┐
│ Domain   │ Auggie Pain │ Auggie Why    │ LeadMagic   │ Auggie       │
│          │ Score       │               │ Contact     │ Sequence     │
├──────────┼─────────────┼───────────────┼─────────────┼──────────────┤
│ acme.com │ 9           │ Scaling + 4mo │ mike@acme   │ Mike - saw...│
│          │             │ backend role  │             │              │
└──────────┴─────────────┴───────────────┴─────────────┴──────────────┘
```

### Success Criteria
- Listed in Clay marketplace
- 20+ Clay users using Auggie enrichment within 60 days of listing
- Clay workflow template published and discoverable

---

## Phase 7.5: Score Calibration
**Status:** Planned

Make the scoring more accurate and consistent by adding reference examples, requiring cited evidence, and penalizing unsupported scores. No new data sources — just smarter prompts.

### Step 1: Audit current scoring
- [ ] Pull 20-30 existing research documents and review their scores
- [ ] Identify patterns: are scores clustered too high? Too uniform? Missing edge cases?
- [ ] Document what a "good" 90, 70, and 40 actually looks like for each dimension

### Step 2: Add calibration anchors to the scoring prompt
- [ ] Add reference examples for Pain: "A company with 3+ compounding signals and a long-open role = 85-95. A company with one minor signal = 30-50."
- [ ] Add reference examples for Fit: "Exact ICP match on size, industry, and personas = 85-95. Adjacent industry, partial overlap = 50-70."
- [ ] Add reference examples for Timing: "Series B in last 6 months + hiring spike = 85-95. No funding or hiring signals = 20-40."
- [ ] Include 2-3 concrete scored examples in the prompt so Claude has anchors

### Step 3: Require cited evidence for each score
- [ ] Update prompt to require Claude to list the specific evidence behind each score
- [ ] If Claude can't cite at least one signal for a dimension, score must be below 30
- [ ] Add SCORE_PAIN_EVIDENCE, SCORE_FIT_EVIDENCE, SCORE_TIMING_EVIDENCE fields
- [ ] Parse and store evidence fields alongside scores

### Step 4: Add negative signal awareness
- [ ] Add guidance for absence of signals (no job postings = not growing, no news = stale)
- [ ] Add guidance for anti-signals (recently laid off, shrinking headcount, sunsetting product)
- [ ] These should pull scores down, not just leave them neutral

### Step 5: Validate and tune
- [ ] Re-run 20-30 companies through updated scoring
- [ ] Compare old vs new scores — verify better spread and more justified scores
- [ ] Adjust calibration anchors based on results
- [ ] Spot-check that evidence fields are accurate (not hallucinated)

### Success Criteria
- Score distribution has meaningful spread (not all 60-80)
- Every score above 70 has cited evidence that checks out
- Users can read the evidence and understand why a company scored the way it did

---

## Phase 7.7: Data Sources Expansion
**Status:** Planned

New data sources to strengthen scoring. Firmographics become part of the score composition (not just filters). Trigger events, compliance deadlines, and competitive pressure feed directly into Pain/Fit/Timing scores.

### SEC EDGAR (free — public companies)
- [ ] Integrate EDGAR REST API (JSON, no key needed)
- [ ] Pull recent 8-K filings — leadership changes, M&A, restructuring, layoffs
- [ ] Parse 10-K/10-Q Risk Factors section — companies disclose their own pain signals
- [ ] Extract revenue, headcount, and financial performance from quarterly filings
- [ ] Feed structured trigger events into Timing score
- [ ] Feed Risk Factors into Pain score

### G2 / Capterra Review Scraping
- [ ] Scrape G2 product pages (Firecrawl or BeautifulSoup) — star ratings, review counts
- [ ] Extract negative review themes (scaling issues, poor support, missing features)
- [ ] Pull competitor comparison data and "switching from/to" signals
- [ ] Scrape Capterra as fallback/supplement
- [ ] Feed competitive pressure signals into Pain score

### Federal Register API (free — compliance deadlines)
- [ ] Integrate Federal Register API for new regulations with effective dates
- [ ] Match regulations to company industry classification
- [ ] Extract upcoming compliance deadlines relevant to the company
- [ ] Feed deadline-driven urgency into Timing score

### Firmographic Enrichment (Apollo or Crunchbase)
- [ ] Integrate firmographic API — headcount, funding rounds, revenue, industry, founding date
- [ ] Feed confirmed firmographics into Fit score (remove the 65 cap when data is available)
- [ ] Add funding recency and amount to Timing score
- [ ] Add headcount growth rate as a trigger event signal

---

## Phase 8: Intelligence Orchestration
**Status:** Planned

Transform Auggie into the orchestration layer for sales intelligence. Ingest lists from any source, score by problem signals, push to sequencers.

**Recommended build order:** CSV Upload → HubSpot → Instantly → Slack/Zapier → Salesforce → Apollo → Ocean.io → Chrome Extension

### Stage 1: CSV Upload (foundation)
- [ ] Build CSV upload UI — accept a file of company domains
- [ ] Parse CSV, validate URLs, create a list automatically
- [ ] Trigger bulk analysis on upload (reuse existing list analysis pipeline)
- [ ] Display results in a list view with score sorting/filtering

### Stage 2: CRM Ingest — HubSpot
- [ ] Register Auggie as a HubSpot app (OAuth)
- [ ] Build HubSpot OAuth flow (connect account)
- [ ] Pull companies from HubSpot via API
- [ ] Let user select which companies/lists to import
- [ ] Create Auggie list from imported companies, trigger analysis
- [ ] Write scores back to HubSpot company records (custom properties)

### Stage 3: CRM Ingest — Salesforce
- [ ] Register Auggie as a Salesforce Connected App
- [ ] Build Salesforce OAuth flow
- [ ] Pull accounts from Salesforce
- [ ] Import flow (same pattern as HubSpot)
- [ ] Write scores back to Salesforce account records

### Stage 4: Prospecting Tool Ingest
- [ ] Apollo API integration — import saved lists
- [ ] Ocean.io API integration — import lookalike audiences

### Stage 5: Execute — First Sequencer
- [ ] Pick sequencer (Instantly likely first — simple API, popular with ICP)
- [ ] Build OAuth or API key connection flow
- [ ] Push contacts + sequences to the sequencer from a completed list
- [ ] UI: "Send to Instantly" button on filtered list view

### Stage 6: Notifications
- [ ] Slack integration — webhook notifications (research complete, high-pain alert)
- [ ] Zapier/Make webhook triggers (covers long tail without custom integrations)

### Stage 7: Chrome Extension
- [ ] Chrome extension — research any company from their website
- [ ] Show scores + talking points in a sidebar popup

### Future Execute Integrations
- [ ] Outreach — push sequences
- [ ] Salesloft — push sequences
- [ ] HubSpot — push to sequences
- [ ] Salesforce — sync research to account records

### Future Enrich Integrations
- [ ] LeadMagic — contacts for high-pain accounts only (re-enable after data quality improves)
- [ ] Apollo — contact enrichment
- [ ] Clearbit — firmographic enrichment

---

## Phase 9: Bulk Workflows & Lists UI
**Status:** Future (core to enterprise)

### List Management UI
- [ ] "Create New List" with import sources (Ocean, Clay, Apollo, CRMs, CSV)
- [ ] List view with pain scores and status
- [ ] Filter/sort by pain score, industry, stage
- [ ] Bulk actions (research all, enrich all, write all, send all)

### Bulk Processing Pipeline
Upload list → Analyze all → Enrich high-pain → Write sequences → Push to sequencer

**The full workflow:**
```
1. INGEST:  Import 500 accounts from Ocean.io
2. ANALYZE: Research all, score by pain (async, parallel)
3. FILTER:  User reviews, selects 87 high-pain accounts
4. ENRICH:  Call LeadMagic for contacts on 87 accounts
5. WRITE:   Generate sequences for 87 accounts
6. EXECUTE: Push 87 sequences + contacts to Instantly
```

### Opportunity Scoring (Full tier only)

Composite score built from data Auggie actually has. Not available on Free/Credits tiers.

**Three factors:**

**Pain (40%) - "Are they hurting?"**
Data: Tech stack, job postings, news, website content
- Existential data points (Data Cocktail combinations)
- Roles open 4+ months
- Competitor detected in stack
- Scaling/performance signals
- Deprecated tech detected

**Fit (35%) - "Should we be selling to them?"**
Data: User's onboarding ICP context + scraped company data
- Industry matches ICP
- Company size matches target
- Target persona titles in job postings
- Tech stack overlaps with product use case
- Stated problems match what seller solves

**Timing (25%) - "Should we call now or later?"**
Data: News, job postings, investor relations
- Funding announced in last 6 months
- Hiring spike (5+ relevant roles)
- Leadership change / reorg signals
- Active vendor evaluation signals
- Role age (new = building, old = struggling)

**Composite formula:**
```
Opportunity Score = (Pain × 0.40) + (Fit × 0.35) + (Timing × 0.25)
```

**Output format:**
```
OPPORTUNITY SCORE: 8.1 / 10

Pain:    9/10  (PostgreSQL scaling + 4mo backend role)
Fit:     8/10  (mid-market SaaS, target personas present)
Timing:  7/10  (Series B announced, hiring spike)

Summary: Strong pain signals with high ICP fit.
Recent Series B creates urgency.
```

**Implementation:**
- [ ] Add scoring criteria to Claude research prompt
- [ ] Parse structured score from research output
- [ ] Add pain_score, fit_score, timing_score, opportunity_score to models
- [ ] Add scoring columns to database
- [ ] Display score on research document (Full tier only)
- [ ] Gate scoring behind tier check
- [ ] Make weights configurable per customer (future)
- [ ] Prioritized list: "Call these 47 first"

### API
```
POST /api/lists
{ "name": "Q1 Targets", "source": "csv", "companies": [...] }
→ { "list_id": "list_abc123" }

POST /api/lists/{list_id}/analyze
→ { "status": "processing", "completed": 47, "total": 500 }

GET /api/lists/{list_id}/accounts?min_pain_score=7
→ [{ "domain": "acme.com", "pain_score": 9, "research_id": "..." }, ...]

POST /api/lists/{list_id}/enrich
{ "account_ids": [...], "provider": "leadmagic" }

POST /api/lists/{list_id}/execute
{ "account_ids": [...], "destination": "instantly" }
```

### Database
```sql
CREATE TABLE lists (
  id TEXT PRIMARY KEY,
  user_id BIGINT REFERENCES users(id),
  name TEXT,
  source TEXT,
  status TEXT DEFAULT 'created',
  total_accounts INTEGER DEFAULT 0,
  analyzed INTEGER DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE list_accounts (
  id BIGSERIAL PRIMARY KEY,
  list_id TEXT REFERENCES lists(id),
  company_url TEXT,
  pain_score INTEGER,
  pain_categories JSONB,
  document_id BIGINT REFERENCES research_documents(id),
  contact_data JSONB,
  sequence_id BIGINT,
  status TEXT DEFAULT 'pending',
  enriched_at TIMESTAMPTZ,
  executed_at TIMESTAMPTZ
);
```

### Other Advanced Features
- [ ] Saved research templates
- [ ] Competitor tracking over time
- [ ] AI chat follow-up on research
- [ ] PDF export

---

## Phase 10: Team Accounts
**Status:** Planned

Enable businesses to have multiple users under one organization.

- [ ] Org/team data model
- [ ] Invite team members
- [ ] Role-based access (Admin, Member, Viewer)
- [ ] Centralized billing (one bill per org)
- [ ] Shared materials library
- [ ] Usage dashboard (who researched what)

---

## Phase 11: Enterprise Auth & Security
**Status:** Planned

Required for enterprise sales.

- [ ] SSO (SAML/OIDC) - Okta, Azure AD, Google Workspace
- [ ] SCIM user provisioning
- [ ] Audit logs
- [ ] Data retention controls
- [ ] SOC 2 compliance prep

---

## Pricing

### Philosophy: Consumption Model

Pay per research. No subscriptions. Guaranteed margins on every call.
UI and API use the same credits. Where you work doesn't change what you pay.

### Two Tiers

| Tier | Price | Includes | Access |
|------|-------|----------|--------|
| **Basic** | $1.00 | Research + sequence (BYOC) | UI + API |
| **Full** | $1.50 | Research + Opportunity Score + LeadMagic contact + sequence | UI + API |

**Free:** 1 Basic research to try it out (no API).

**BYOC** = Bring Your Own Contact (you provide contact info for sequence personalization)

### What Each Tier Returns

**Basic ($1.00)**
```
You provide: Domain
Auggie returns: Research, talking points, sequence
No scoring. No contact enrichment.
```

**Full ($1.50)**
```
You provide: Domain
Auggie returns:
  - Opportunity Score (Pain + Fit + Timing)
  - Research document
  - Contact via LeadMagic
  - Personalized sequence
```

**The gate:** Basic users see the research and a locked Opportunity Score.
$0.50 more unlocks scoring, contact, and full personalization.

### Volume Pricing

| Volume | Basic | Full |
|--------|-------|------|
| 1-99 | $1.00 | $1.50 |
| 100+ | $0.85 | $1.25 |
| Enterprise | Custom | Custom |

### Unit Economics

**Basic ($1.00):**
| Cost Component | Estimate |
|----------------|----------|
| Firecrawl (scraping) | $0.10-0.15 |
| Claude Opus 4 (research) | $0.45-0.60 |
| SerpAPI (news) | $0.01 |
| Claude Sonnet 4 (sequence) | $0.06 |
| **COGS** | **$0.62-0.82** |
| **Revenue** | **$1.00** |
| **Margin** | **18-38%** |

**Full ($1.50):**
| Cost Component | Estimate |
|----------------|----------|
| Firecrawl (scraping) | $0.10-0.15 |
| Claude Opus 4 (research + scoring) | $0.48-0.65 |
| SerpAPI (news) | $0.01 |
| Claude Sonnet 4 (sequence) | $0.06 |
| LeadMagic (contact) | $0.10-0.20 |
| **COGS** | **$0.75-1.07** |
| **Revenue** | **$1.50** |
| **Margin** | **29-50%** |

Positive margin on every research. No utilization risk. No subscription management.

### Admin Accounts
Internal users can be granted unlimited free usage:
```sql
UPDATE users SET is_admin = TRUE WHERE email = 'your@email.com';
```

---

## Infrastructure Hygiene (Ongoing)
**Status:** Planned

General infrastructure hardening and operational improvements. Not a phase — just a running list to tackle as needed.

### Cloudflare
- [ ] Proxy app through Cloudflare (orange cloud) — DDoS protection, SSL termination, caching
- [ ] Set up Cloudflare DNS for auggie.app / auggie.tools
- [ ] Enable WAF rules for API endpoints
- [ ] Configure rate limiting at edge (complement in-app rate limiting)
- [ ] Set up page rules / cache rules for static assets

### Monitoring & Observability
- [ ] Error tracking (Sentry or similar)
- [ ] Uptime monitoring / health checks
- [ ] Request latency logging per endpoint
- [ ] Database query performance monitoring

### Database
- [ ] Set up automated backups (verify Neon config)
- [ ] Add database connection pooling review
- [ ] Index audit for slow queries

### Security
- [ ] Rotate API secrets on a schedule
- [ ] Review CORS configuration
- [ ] Add Content-Security-Policy headers
- [ ] Dependency vulnerability scanning (Dependabot or similar)

---

## Priority Timeline

| Timeframe | Phase | Goal |
|-----------|-------|------|
| ✅ Done | Phase 1 | Production launch |
| ✅ Done | Phase 2 | Contact enrichment (disabled — bad data quality) |
| ✅ Done | Phase 3 | Writing workflow |
| ✅ Done | Phase 4 | Microsoft OAuth |
| ✅ Done | Phase 5 | Public API (async jobs, webhooks, sequences, rate limiting) |
| ✅ Done | Phase 6 | Bulk research, lists API, docs, SDK |
| Next | Phase 7 | Clay Marketplace (30-60 day onboarding) |
| Next | Phase 7.5 | Score calibration (anchors, evidence, negative signals) |
| Next | Phase 7.7 | Data sources (EDGAR, G2, Federal Register, firmographics) |
| After | Phase 8 | Intelligence orchestration (ingest/enrich/execute integrations) |
| After | Phase 9 | Bulk workflows UI |
| Later | Phase 10 | Team accounts |
| Later | Phase 11 | Enterprise security (SSO, SCIM, audit logs)

---

## Future Consideration: Free Tier Monetization

Ideas to monetize free users without converting them to paid:

### 1. Watermarked Exports
- [ ] Add "Powered by Auggie - auggie.tools" to free user research docs
- [ ] Remove watermark for Pro users
- Every shared doc = free marketing

### 2. Affiliate Revenue
- [ ] Partner with CRMs (HubSpot, Salesforce)
- [ ] Partner with sales tools (Apollo, Outreach, Salesloft)
- [ ] Add affiliate links to recommended tools in research output
- Earn commission when free users sign up

### 3. Gated Features (Recommended)
- [ ] Free tier: Basic research only
- [ ] Gate contacts behind Pro ("Upgrade to see key contacts")
- [ ] Gate email sequence behind Pro ("Upgrade to generate outreach")
- Research hooks them, premium features convert them

### 4. Lead Intelligence (Proceed with caution)
- [ ] Anonymized/aggregated data on companies being researched
- [ ] Sell to sales intelligence platforms
- Privacy-sensitive - requires careful consideration

### 5. API / White-label
- [ ] Let other sales tools embed Auggie research
- [ ] Charge per API call or rev share
- [ ] "Powered by Auggie" in partner products
