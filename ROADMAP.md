# Auggie Product Roadmap

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

## Phase 6: Integrations
**Status:** Planned

Connect Auggie to sales team workflows.

- [ ] Salesforce integration (push research to accounts)
- [ ] HubSpot integration
- [ ] Slack notifications
- [ ] API access for customers
- [ ] Chrome extension
- [ ] Zapier/Make connectors

---

## Phase 7: Advanced Features
**Status:** Future

- [ ] Bulk research API (see sketch below)
- [ ] Saved research templates
- [ ] Competitor tracking over time
- [ ] AI chat follow-up on research
- [ ] PDF export

### Bulk Research API (Sketched)

Upload CSV of 100 companies → get research docs for all of them.

**API:**
```
POST /api/bulk-research
{ "companies": ["acme.com", "globex.com", ...] }
→ { "batch_id": "batch_abc123", "status": "queued" }

GET /api/bulk-research/batch_abc123
→ { "status": "processing", "completed": 47, "total": 100 }

GET /api/bulk-research/batch_abc123/download
→ ZIP file with all markdown research docs
```

**Database:**
```sql
CREATE TABLE bulk_batches (
  id TEXT PRIMARY KEY,
  user_id BIGINT REFERENCES users(id),
  status TEXT DEFAULT 'queued',
  total INTEGER,
  completed INTEGER DEFAULT 0,
  failed INTEGER DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE bulk_batch_items (
  id BIGSERIAL PRIMARY KEY,
  batch_id TEXT REFERENCES bulk_batches(id),
  company_url TEXT,
  document_id BIGINT REFERENCES research_documents(id),
  status TEXT DEFAULT 'pending',
  error TEXT
);
```

**Pricing:** 1 credit per company (or bulk discount: 100 = 80 credits)

**Effort:** ~1 day for v1 (API only, sequential processing, email on completion)

---

## Pricing (Current - Consumption Model)

| Tier | Price | Credits | Features |
|------|-------|---------|----------|
| Free | $0 | 1 credit | Full research, PVP emails |
| Credits | $10 | 10 credits | Same features, pay as you go |

Simple consumption model - no subscriptions, no monthly limits. Users buy credits when they need them.

### Admin Accounts
Internal users can be granted unlimited free usage:
```sql
UPDATE users SET is_admin = TRUE WHERE email = 'your@email.com';
```

### Unit Economics (per research)
| Cost Component | Estimate |
|----------------|----------|
| Firecrawl (scraping) | $0.10-0.15 |
| Claude Opus 4 (research) | $0.45-0.60 |
| Claude Sonnet 4 (emails) | $0.06 |
| OpenAI embeddings | $0.01 |
| **Total COGS** | **$0.62-0.82** |
| **Revenue** | **$1.00** |
| **Gross Margin** | **18-38%** |

Free tier cost: ~$0.65/user (1 research). Break-even at ~10% conversion rate.

### Future Tiers (Not Yet Built)
| Tier | Price | Credits | Features |
|------|-------|---------|----------|
| Team | TBD | Shared pool | Shared materials, team dashboard |
| Enterprise | Custom | Volume pricing | SSO, API, SLA |

---

## Priority Timeline

| Timeframe | Phase | Goal |
|-----------|-------|------|
| ✅ Done | Phase 1 | Production launch with full v2 |
| ~~Done~~ | Phase 2 | Apollo contacts (removed for margins) |
| ✅ Done | Phase 3 | Writing workflow |
| ✅ Done | Phase 3.5 | Microsoft OAuth for MSPs |
| ✅ Done | - | Admin accounts, unit economics optimization |
| Next | Phase 4 | Team accounts |
| Month 2-3 | Phase 6 | CRM integrations |
| Month 3+ | Phase 5 | Enterprise security |

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
