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

## Current Status: v2 LIVE IN PRODUCTION
- Core research generation working (Claude Opus 4)
- Materials upload & RAG working
- Writing workflow (PVP email sequences) working
- Consumption pricing (1 free, $10 for 10 credits) working
- Admin accounts (unlimited usage for internal users)
- Live at https://auggie.tools

---

## Phase 1: Production Launch
**Status:** Ready to deploy

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

## Phase 2: Contact Enrichment (Apollo)
**Status:** REMOVED (margin optimization)

Was adding key contacts via Apollo.io API, but removed to improve unit economics.

### Why Removed
- Added $0.10-0.50 per research in API costs
- Most users already have their own contact tools (LinkedIn Sales Nav, ZoomInfo, Apollo)
- Core value is research quality, not contact data
- Code remains in services/apollo.py if needed later

### Original Features (archived)
- Query Apollo API for contacts at target domain
- Filter by user's target personas
- Display in research: name, title, email status

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

## Phase 3.5: Microsoft OAuth
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

## Phase 4: Team Accounts
**Status:** Planned

Enable businesses to have multiple users under one organization.

- [ ] Org/team data model
- [ ] Invite team members
- [ ] Role-based access (Admin, Member, Viewer)
- [ ] Centralized billing (one bill per org)
- [ ] Shared materials library
- [ ] Usage dashboard (who researched what)

---

## Phase 5: Enterprise Auth & Security
**Status:** Planned

Required for enterprise sales.

- [ ] SSO (SAML/OIDC) - Okta, Azure AD, Google Workspace
- [ ] SCIM user provisioning
- [ ] Audit logs
- [ ] Data retention controls
- [ ] SOC 2 compliance prep

---

## Phase 6a: Public API
**Status:** Planned (NEXT)
**PRD:** [PRD_API.md](./PRD_API.md)

The API is the foundation for enterprise. Without it, no Clay integration, no bulk workflows, no "intelligence layer" positioning.

### Core Deliverables

**Week 1-2: Core API**
- [ ] API key generation + management
- [ ] `POST /v1/research` - Create research, get pain score
- [ ] `GET /v1/research/{id}` - Retrieve research
- [ ] Pain score synthesis (update Claude prompt)
- [ ] Rate limiting + error handling
- [ ] Credit deduction

**Week 3: Sequences + Webhooks**
- [ ] `POST /v1/research/{id}/sequence` - Generate sequence
- [ ] Webhook delivery system
- [ ] Async research option

**Week 4: Bulk/Lists**
- [ ] `POST /v1/lists` - Create list from domains
- [ ] `GET /v1/lists/{id}/accounts` - Get accounts with pain scores
- [ ] Background job processing
- [ ] Progress webhooks

**Week 5: Polish + Docs**
- [ ] API documentation (Mintlify)
- [ ] Python SDK (basic)
- [ ] Clay integration guide
- [ ] Dashboard: API key management
- [ ] Dashboard: Usage tracking

### Key API Outputs

| Endpoint | Returns |
|----------|---------|
| `/v1/research` | pain_score, pain_summary, research, talking_points |
| `/v1/research/{id}/sequence` | 3-email sequence personalized to contact |
| `/v1/lists/{id}/accounts` | All accounts sorted by pain score |

### Success Criteria
- 10 API customers in 90 days
- 1,000 API calls/month
- < 1% error rate
- P95 latency < 45 seconds

---

## Phase 6a.1: Clay Marketplace
**Status:** Planned (start when API is stable, ~week 5)
**Timeline:** 30-60 day onboarding process (runs in background)

Become an official enrichment provider in Clay's marketplace. This is the primary distribution channel for API adoption.

### Why Clay First
- 150+ enrichment providers, but none do pain-based scoring
- Clay users are exactly our ICP: RevOps teams building outbound workflows
- Marketplace listing = free distribution to Clay's entire customer base
- Co-marketing starts after integration is live

### Steps
- [ ] Build API (Phase 6a prerequisite)
- [ ] Contact Clay Data Partnerships Team
- [ ] Join shared Slack channel with Clay engineer
- [ ] Build Clay-compatible enrichment endpoint
- [ ] Test integration end-to-end
- [ ] Publish to Clay marketplace (site, docs, product search)
- [ ] Create Clay workflow template: "Pain-Based Outbound"

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

## Phase 6b: Intelligence Orchestration (Enterprise)
**Status:** Planned (after 6a)

Transform Auggie into the orchestration layer for sales intelligence.

### Ingest Integrations (list sources)
- [ ] Ocean.io - Import lookalike audiences
- [ ] Clay - Import tables (uses API)
- [ ] Apollo - Import saved lists
- [ ] HubSpot - Import companies
- [ ] Salesforce - Import accounts
- [ ] CSV upload - Bulk import

### Enrich Integrations (contact data)
- [ ] LeadMagic - Get contacts for high-pain accounts only
- [ ] Apollo - Contact enrichment
- [ ] Clearbit - Firmographic enrichment

### Execute Integrations (sequencers)
- [ ] Instantly - Push sequences + contacts
- [ ] Outreach - Push sequences
- [ ] Salesloft - Push sequences
- [ ] HubSpot - Push to sequences
- [ ] Salesforce - Sync research to account records

### Other
- [ ] Slack notifications (research complete, high-pain alert)
- [ ] Zapier/Make connectors
- [ ] Chrome extension

---

## Phase 7: Bulk Workflows & Lists
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

### Pain Scoring
- [ ] Numeric pain score (1-10) based on existential data points
- [ ] Pain categories (scaling, cost, technical debt, competitive, organizational)
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

## Pricing

### Philosophy: One Product, Two Interfaces

UI and API are the same product. Same features at each tier, different access method.
Where you work (auggie.tools vs Clay) shouldn't change what you pay.

### Tier Structure

| Tier | Price | Volume | Enrichment | Access | Features |
|------|-------|--------|------------|--------|----------|
| Free | $0 | 1 research | None | UI only | Try it out |
| Credits | $10/10 | Pay as you go | None (BYOC) | UI + API | Individual users |
| Pro | $99/mo | 100/mo | LeadMagic included | UI + API | Full orchestration |
| Team | $299/mo | 500/mo | LeadMagic included | UI + API | 10 seats, shared materials |
| Enterprise | Custom | Unlimited | Everything included | UI + API | SSO, bulk, SLA |

**BYOC** = Bring Your Own Contact (customer provides contact info for sequences)

### What Each Tier Unlocks

**Free / Credits (BYOC)**
```
You provide: Domain
Auggie returns: Pain score, research, talking points
You provide: Contact info
Auggie returns: Personalized sequence
```

**Pro and above (Full Orchestration)**
```
You provide: Domain
Auggie returns: Pain score, research, contact (via LeadMagic), sequence - all in one
```

### Unit Economics

**Base research (all tiers):**
| Cost Component | Estimate |
|----------------|----------|
| Firecrawl (scraping) | $0.10-0.15 |
| Claude Opus 4 (research) | $0.45-0.60 |
| SerpAPI (news) | $0.01 |
| Claude Sonnet 4 (sequence) | $0.06 |
| **COGS (BYOC)** | **$0.62-0.82** |

**With enrichment (Pro+):**
| Cost Component | Estimate |
|----------------|----------|
| Base COGS | $0.62-0.82 |
| LeadMagic (contact) | $0.10-0.20 |
| **COGS (Full)** | **$0.72-1.02** |

**Margin by tier:**
| Tier | Revenue/research | COGS | Margin |
|------|------------------|------|--------|
| Credits | $1.00 | $0.62-0.82 | 18-38% |
| Pro ($99/100) | $0.99 | $0.72-1.02 | Break-even to 27% |
| Team ($299/500) | $0.60 | $0.72-1.02 | Negative at full usage |
| Enterprise | Custom | $0.72-1.02 | Price for margin |

**Note:** Team/Enterprise margins work because most customers don't use full allocation.
At 60% utilization, Team margin is healthy. Enterprise priced per deal.

### Admin Accounts
Internal users can be granted unlimited free usage:
```sql
UPDATE users SET is_admin = TRUE WHERE email = 'your@email.com';
```

---

## Priority Timeline

| Timeframe | Phase | Goal |
|-----------|-------|------|
| ✅ Done | Phase 1 | Production launch with full v2 |
| ~~Done~~ | Phase 2 | Apollo contacts (removed for margins) |
| ✅ Done | Phase 3 | Writing workflow |
| ✅ Done | Phase 3.5 | Microsoft OAuth for MSPs |
| ✅ Done | - | Admin accounts, unit economics optimization |
| **NEXT** | **Phase 6a** | **Public API (foundation for everything)** |
| Week 1-2 | Phase 6a | Core API + pain score |
| Week 3 | Phase 6a | Sequences + webhooks |
| Week 4 | Phase 6a | Bulk lists |
| Week 5 | Phase 6a | Docs + Clay integration guide |
| Week 5 | Phase 6a.1 | Apply to Clay Marketplace (30-60 day onboarding) |
| Month 2 | Phase 6b | Ingest integrations (Clay, CSV) |
| Month 2 | Phase 7 | Bulk workflows UI |
| Month 2-3 | Phase 6b | Execute integrations (Instantly) |
| Month 3 | Phase 4 | Team accounts |
| Month 3+ | Phase 6b | Enrich integrations (LeadMagic) |
| Month 4+ | Phase 5 | Enterprise security (SSO, SCIM)

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
