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

## Current Status: v2 LIVE IN PRODUCTION + PUBLIC API + CHROME EXTENSION + TEAM ACCOUNTS
- Core research generation working (Claude Opus 4, temperature 0.25)
- Materials upload & RAG working
- Writing workflow (PVP email sequences) working
- Consumption pricing (1 free, $10 for 10 credits) working
- Admin accounts (unlimited usage for internal users)
- Public API with async jobs, webhooks, rate limiting, sequence generation
- Chrome extension with real-time progress tracking and background polling
- Scoring recalibrated: raised Fit cap (65→80), shifted anchors up ~10pts, removed sync research route
- Team accounts: orgs, invites, role-based access, shared credits, usage dashboard
- G2/Capterra review scraping removed (low signal-to-cost ratio)
- Wappalyzer optimized: trimmed subdomain list, HEAD-first discovery
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
**Status:** Partially Complete (technical work done, marketplace onboarding remaining — see Phase 13)

Technical foundation for Clay integration is complete. Remaining marketplace onboarding steps moved to Phase 13 to run in the background.

### Completed
- [x] Build API (Phase 5 prerequisite)
- [x] Build Clay-compatible synchronous enrichment endpoint
- [x] Add 24-hour caching to avoid duplicate costs
- [x] Update docs and Clay guide with sync endpoint
- [x] Create /integrations/clay landing page

---

## Phase 7.5: Score Calibration
**Status:** Done

Make the scoring more accurate and consistent by adding reference examples, requiring cited evidence, and penalizing unsupported scores.

### Step 1: Audit current scoring ✅
- [x] Reviewed 12 research documents across diverse companies
- [x] Identified clustering at round numbers (20, 25, 45, 75)
- [x] Found Timing scores defaulting to 20 when zero signals present
- [x] Found Fit scores ignoring the 65 cap without confirmed firmographics
- [x] Found Pain scores lacking middle range (jumping from 25 to 72)

### Step 2: Add calibration anchors to the scoring prompt ✅
- [x] Calibration anchors for Pain, Fit, and Timing with specific score ranges
- [x] 3 concrete scored examples (fintech high-scorer, regional bank low-scorer, baseball analytics low-scorer)
- [x] Anti-clustering guidance: never default to round numbers, use precise scores

### Step 3: Require cited evidence for each score ✅
- [x] SCORE_PAIN_EVIDENCE, SCORE_FIT_EVIDENCE, SCORE_TIMING_EVIDENCE fields
- [x] Evidence parsed and stored alongside scores
- [x] Evidence displayed in UI via expandable "Score evidence" section

### Step 4: Add negative signal awareness ✅
- [x] Absence of signals = strong negative (zero timing signals → below 15)
- [x] Anti-signals guidance (layoffs, budget cuts, hiring freeze → 0-14)
- [x] Fit cap of 80 without confirmed firmographic data (raised from 65)

### Step 5: Validate and tune ✅
- [x] Audited 12 companies, identified clustering issues
- [x] Updated prompt with anti-clustering, lower floors, stricter caps
- [x] Pushed to production for re-testing

### Step 6: Recalibration (Jan 2026) ✅
- [x] Set temperature to 0.25 (was default 1.0 — caused ±13pt variance between runs)
- [x] Raised Fit cap from 65 to 80 — most companies lack SEC filings, cap was filtering out good prospects
- [x] Shifted all calibration anchors up ~10 points to reduce false negatives
- [x] Raised ceiling guidance from 70 to 75
- [x] Updated example scores to match new calibration
- [x] Validated: adaptivebiotech.com scores 77 composite consistently across runs

---

## Phase 7.7: Data Sources Expansion
**Status:** Done

New data sources to strengthen scoring. Trigger events, compliance deadlines, and competitive pressure feed directly into Pain/Fit/Timing scores. All sources fail gracefully — if a source errors or returns nothing, the pipeline continues.

### SEC EDGAR (free — public companies) ✅
- [x] Integrate EDGAR REST API (JSON, no key needed)
- [x] Cache company_tickers.json for fast public/private company detection
- [x] Domain-aware company name matching (e.g., datadoghq.com → Datadog, Inc.)
- [x] Pull recent 8-K filings with item code descriptions and high-signal markers
- [x] Parse 10-K Risk Factors section — companies disclose their own pain signals
- [x] Extract financial filing timeline (10-K/10-Q dates)
- [x] Feed into Claude prompt as high-confidence data source
- [x] All data feeds into Pain score (Risk Factors) and Timing score (8-K events)

### G2 / Capterra Review Scraping (Removed)
- [x] ~~Search and scrape G2 product pages via Firecrawl search~~
- [x] ~~Search and scrape Capterra product pages via Firecrawl search~~
- Removed in Phase 11 work — low signal-to-cost ratio. Firecrawl search calls ($0.04 each) rarely returned useful competitive data. EDGAR + Federal Register provide higher-confidence signals.

### Federal Register API (free — compliance deadlines) ✅
- [x] Integrate Federal Register API for rules and proposed rules
- [x] Match regulations to company industry via SIC code (from EDGAR when available)
- [x] SIC-to-topic mapping for 20+ industry categories
- [x] Extract upcoming compliance deadlines with effective dates
- [x] Feed deadline-driven urgency into Timing score

### Firmographic Enrichment (Apollo or Crunchbase)
_Deferred — EDGAR already provides financials for public companies, and the existing Fit score cap handles the private company case. Will revisit if scoring calibration (Phase 7.5) reveals a gap._

---

## Phase 8: Intelligence Orchestration
**Status:** Stages 1–6 Complete

Transform Auggie into the orchestration layer for sales intelligence. Ingest lists from any source, score by problem signals, push to sequencers.

**Build order:** CSV Upload → HubSpot → Instantly → Slack/Zapier → Salesforce → Apollo → Ocean.io → Chrome Extension

### Stage 1: CSV Upload (foundation) ✅
- [x] Build CSV upload UI — accept a file of company domains
- [x] Parse CSV, validate URLs, create a list automatically
- [x] Trigger bulk analysis on upload (reuse existing list analysis pipeline)
- [x] Display results in a list view with score sorting/filtering

### Stage 2: CRM Ingest — HubSpot ✅
- [x] Register Auggie as a HubSpot app (OAuth)
- [x] Build HubSpot OAuth flow (connect account)
- [x] Pull companies from HubSpot via API
- [x] Let user select which companies/lists to import
- [x] Create Auggie list from imported companies, trigger analysis
- [x] Write scores back to HubSpot company records (custom properties)

### Stage 3: CRM Ingest — Salesforce ✅
- [x] Register Auggie as a Salesforce Connected App
- [x] Build Salesforce OAuth flow
- [x] Pull accounts from Salesforce
- [x] Import flow (same pattern as HubSpot)
- [x] Write scores back to Salesforce account records

### Stage 4: Prospecting Tool Ingest ✅
- [x] Apollo API integration — import saved lists
- [x] Ocean.io API integration — import lookalike audiences

### Stage 5: Execute — First Sequencer ✅
- [x] Pick sequencer (Instantly likely first — simple API, popular with ICP)
- [x] Build OAuth or API key connection flow
- [x] Push contacts + sequences to the sequencer from a completed list
- [x] UI: "Send to Instantly" button on filtered list view

### Stage 6: Notifications ✅
- [x] Slack integration — webhook notifications (research complete, high-pain alert)
- [x] Zapier/Make webhook triggers (covers long tail without custom integrations)

### Stage 7: Chrome Extension ✅
- [x] Chrome extension — research any company from their website
- [x] Popup UI with 6 states (no key, loading, excluded, not researched, researching, completed)
- [x] API key auth via options page with validation
- [x] Background service worker polls for completion (survives popup close)
- [x] Real-time pipeline progress steps (scraping → analyzing → enriching → generating)
- [x] Score display (composite, pain, fit, timing) with progress bars
- [x] Badge shows composite score on extension icon (color-coded)
- [x] 24h local cache by domain to avoid duplicate charges
- [x] Domain exclusion list (google, linkedin, twitter, etc.)
- [x] Copy scores to clipboard, open full research in auggie.tools
- [x] Polish pass: timer memory leak fix, storage/API error hardening, input validation, clipboard safety

### Future Execute Integrations
_Moved to Phase 11.5 (testing) and Phase 11.75 (new sequencers)._

### Future Enrich Integrations
- [ ] LeadMagic — contacts for high-pain accounts only (re-enable after data quality improves)
- [ ] Apollo — contact enrichment
- [ ] Clearbit — firmographic enrichment

---

## Phase 8.5: UX Polish
**Status:** Complete (P0 + P1 + P2 shipped)

Fix friction points that hurt activation, retention, and daily usability. Grouped by impact.

### P0 — Conversion blockers

- [x] **Research progress indicator** — Async job + polling progress page with 5 animated steps and spinner on final step while job completes.
- [x] **Friendly error pages** — Styled error template for 400/402/404/500 with friendly titles, credit refund note, and action buttons.
- [x] **Low-credit warning banner** — Dismissible yellow banner when credits < 3, remembers dismissal in localStorage.
- [x] **Payment success confirmation** — Toast via `?payment=success` URL param with history.replaceState cleanup.
- [x] **Duplicate research warning** — Client-side check before submission with confirm dialog and link to existing document.

### P1 — Daily friction

- [x] **CSV export from list view** — "Export CSV" button downloads all accounts with scores, status, and company names.
- [x] **Document search** — Client-side search input in sidebar filtering recent docs by company name.
- [x] **Remove PDF export** — Removed dead `/document/{id}/pdf` route (no UI button existed). Can revisit with WeasyPrint later if needed.
- [x] **Inline email editing** — Outreach modal renders emails as editable subject input + body textarea. Copy All reads current values.
- [x] **Retry failed list items** — Per-item "Retry" button on failed list accounts with AJAX + toast feedback.

### P2 — Quality of life

- [x] **Toast/flash notification system** — Reusable toast component in `base.html` with success/error/warning/info types, auto-dismiss, and manual close.
- [x] **Onboarding validation** — Client-side validation requiring at least one selection per checkbox group. Add tooltips explaining how each field affects research quality.
- [x] **Webhook config UI** — Webhooks exist in the API but can only be configured via API calls. Add a simple form in Settings or API Keys page.
- [x] **Mobile-responsive tables** — List view and API keys tables (7 columns each) overflow on mobile. Collapse to card layout or hide non-critical columns.
- [x] **Bulk list actions** — Checkboxes + toolbar for selecting multiple list accounts to export, delete, or retry.
- [x] **Materials search & preview** — Add search bar and "View" button showing extracted text. Users can't find or inspect materials at scale.

---

## Phase 13: Clay Marketplace
**Status:** Planned (runs in background)
**Timeline:** 30-60 day onboarding process

Complete the Clay marketplace onboarding. Technical integration is done (Phase 7). This is the external partnership process.

### Steps
- [ ] Contact Clay Data Partnerships Team
- [ ] Join shared Slack channel with Clay engineer
- [ ] Test integration end-to-end with Clay team
- [ ] Publish to Clay marketplace
- [ ] Create Clay workflow template: "Problem-Signal Prospecting"
- [ ] Feed PVP examples into outreach generation prompt — give the writing service concrete pain-value proposition examples so generated emails follow proven messaging patterns instead of generic output

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

## Phase 10: Pipeline UI + Workflow Automation
**Status:** Complete

Full pipeline stepper UI and automation rules engine. Users can visually step through the pipeline and set rules to automatically act on scored accounts.

### Pipeline Stepper UI ✅
- [x] Visual stepper bar: Score → Enrich → Write Sequences → Execute
- [x] Clickable steps trigger batch operations on all eligible accounts
- [x] Live counts with AJAX polling (scored, enriched, written, pushed)
- [x] Enriched / Sequences columns in list accounts table
- [x] Bulk toolbar buttons: Enrich Selected, Write Sequences
- [x] `enrichment_status` and `outreach_status` columns on `list_accounts`

### Batch Operations ✅
- [x] `POST /lists/{id}/batch-write-sequences` — generates email sequences for scored accounts
- [x] `POST /lists/{id}/batch-enrich` — stub (returns 422 until enrichment provider configured)
- [x] `GET /lists/{id}/pipeline-status` — JSON counts for stepper polling

### Automation Rules Engine ✅
- [x] `automation_rules` table (trigger, conditions, action, config)
- [x] CRUD routes: create, toggle, delete rules
- [x] Automations management page with card-based UI
- [x] Trigger events: `list_complete`, `account_scored`
- [x] Condition filters: composite/pain/fit/timing score thresholds
- [x] Actions: push to Instantly, write sequences, notify Slack
- [x] `automation_runs` audit trail with status, error messages, matched counts
- [x] Recent runs displayed on each rule card
- [x] Rules evaluated automatically after list analysis and per-account scoring
- [x] 36 tests covering automation CRUD, rule evaluation, pipeline status, and batch operations

---

## Phase 11: Team Accounts
**Status:** Complete

Enable businesses to have multiple users under one organization.

### Sub-Phase A: Org Data Model + Migration ✅
- [x] `organizations`, `org_members`, `org_invites` tables
- [x] Auto-wrap every existing user in a 1-person org (race-safe with `SELECT ... FOR UPDATE`)
- [x] Credits moved from `users.bonus_credits` to `organizations.bonus_credits` (org is single source of truth)
- [x] `get_user_by_id()` JOINs org context (role, name, credits, stripe customer)
- [x] New user signup auto-creates 1-person org
- [x] OAuth callbacks auto-accept pending invites
- [x] Billing operations (buy, fulfill, use, refund) all operate on org level
- [x] `org_id` tracked on `fulfilled_sessions` for audit trail
- [x] Admin-only credit purchasing with clear error message for non-admins

### Sub-Phase B: Team Management UI + Invites ✅
- [x] `/settings/team` — members list, pending invites, invite form
- [x] Invite flow: admin enters email + role → 7-day expiry token → invite link
- [x] Accept invite landing page with auto-join on login
- [x] Remove member, change role, revoke invite (admin only)
- [x] Nav: "Team" link in Settings

### Sub-Phase C: Org-Scoped Shared Data ✅
- [x] `org_id` column on `materials`, `material_chunks`, `lists`, `webhooks`
- [x] All org-scoped queries use clean `WHERE org_id = ...` (no NULL fallbacks)
- [x] Research documents remain private (creator-owned); admins can browse all team research
- [x] Integrations remain user-scoped (each user connects their own CRM)

### Sub-Phase D: Usage Dashboard ✅
- [x] `/settings/team/usage` — per-member research count, last activity, total org credits

### API Routes ✅
- [x] `GET /v1/team` — list members
- [x] `POST /v1/team/invite` — invite
- [x] `DELETE /v1/team/members/{id}` — remove
- [x] `PATCH /v1/team/members/{id}` — change role

### Also completed during Phase 11
- [x] Nav cleanup: collapsed to 4 primary links + "More" dropdown
- [x] G2/Capterra review scraping removed (low signal-to-cost)
- [x] Wappalyzer optimized: subdomain list cut from 30+ to 10, HEAD-first discovery

---

## Phase 11.5: Integration Testing
**Status:** Planned

End-to-end testing of existing integrations before adding new ones.

- [ ] HubSpot — import companies, write scores back
- [ ] Salesforce — import accounts, write scores back
- [ ] Instantly — push contacts + sequences
- [ ] Apollo — import saved lists
- [ ] Ocean.io — import lookalike audiences
- [ ] Slack — webhook notifications (research complete, high-pain alert)
- [ ] Webhooks — delivery + HMAC verification
- [ ] Chrome extension — full flow (research, poll, display scores)

---

## Phase 11.75: Sequencer Integrations
**Status:** Planned

Add outbound sequencer integrations so users can push sequences directly from Auggie.

- [ ] Outreach — OAuth connection, push contacts + sequences to Outreach
- [ ] Salesloft — OAuth connection, push contacts + sequences to Salesloft
- [ ] EmailBison — API integration, push sequences

---

## Phase 12: Enterprise Auth & Security
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

_Note: G2/Capterra removal saved ~$0.08/research (2x Firecrawl search calls). Actual COGS closer to $0.54-0.74, margin ~26-46%._

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

_Note: G2/Capterra removal saved ~$0.08/research. Actual COGS closer to $0.67-0.99, margin ~34-55%._

Positive margin on every research. No utilization risk. No subscription management.

### Admin Accounts
Internal users can be granted unlimited free usage:
```sql
UPDATE users SET is_admin = TRUE WHERE email = 'your@email.com';
```

---

## Infrastructure Hygiene (Ongoing)
**Status:** In Progress

General infrastructure hardening and operational improvements. Not a phase — just a running list to tackle as needed.

### Pipeline Performance ✅
- [x] Parallel data collection via `asyncio.gather` (news, EDGAR+FedReg, materials)
- [x] Shared `collect_enrichment_data()` function — single source of truth across all 3 pipelines
- [x] Shared httpx client with connection pooling (eliminates per-request TCP/TLS handshake)
- [x] EDGAR tickers disk cache with 24h TTL (cold start: seconds → milliseconds)
- [x] 10-K Risk Factors parsing offloaded to thread pool (`asyncio.to_thread`)
- [x] Company name extraction centralized in `collect_enrichment_data()`
- [x] Removed blocking sync `POST /research` route — all research now async via background jobs
- [x] Real-time pipeline progress tracking (`progress` column on research_jobs table)

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
| ✅ Done | Phase 7 | Clay Marketplace (technical integration) |
| ✅ Done | Phase 7.5 | Score calibration (anchors, evidence, anti-clustering, concrete examples) |
| ✅ Done | Phase 7.7 | Data sources (SEC EDGAR, Federal Register; G2/Capterra removed) |
| ✅ Done | Phase 8.5 | UX polish — progress indicator, errors, export, search |
| ✅ Done | Phase 8 | Intelligence orchestration — CSV, HubSpot, Instantly, Salesforce, Apollo, Ocean.io, Slack, Chrome Extension |
| ✅ Done | Phase 7.5 Step 6 | Score recalibration (temperature, anchors, Fit cap) |
| Background | Phase 13 | Clay Marketplace onboarding (external process) |
| ✅ Done | Phase 10 | Pipeline UI + workflow automation |
| ✅ Done | Phase 11 | Team accounts (orgs, invites, roles, shared credits, usage dashboard) |
| Next | Phase 11.5 | Integration testing (HubSpot, Salesforce, Instantly, Apollo, etc.) |
| Next | Phase 11.75 | Sequencer integrations (Outreach, Salesloft, EmailBison) |
| Next | — | Speed: evaluate Sonnet 4 for research generation |
| Later | Phase 12 | Enterprise security (SSO, SCIM, audit logs) |

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
