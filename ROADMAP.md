# Auggie Product Roadmap

## Current Status: v2 LIVE IN PRODUCTION
- Core research generation working
- Materials upload & RAG working
- Apollo contact enrichment working
- Writing workflow (email sequences) working
- Stripe billing ($24.99/mo + credit packs) working
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
**Status:** COMPLETE

Add key contacts to research output using Apollo.io API.

### Features
- [x] Query Apollo API for contacts at target domain
- [x] Filter by user's target personas (from onboarding)
- [x] Display in research: name, title, email status
- [ ] Pro-tier only gate (currently enabled for all)

### Output
Returns top 5 ICP-matched contacts with:
- Name (partially masked by Apollo)
- Title
- Email availability indicator
- Seniority/Department when available

### Files Created/Modified
- [x] services/apollo.py - Apollo API integration
- [x] config.py - Added APOLLO_API_KEY
- [x] main.py - Integrated into research flow
- [x] services/claude.py - Added contacts to prompt/output
- [x] models.py - Added key_contacts field
- [x] database.py - Added key_contacts column
- [x] templates/document.html - Added Key Contacts section

### Environment Variables
```
APOLLO_API_KEY=your_key
```

### Notes
- Uses `mixed_people/api_search` and `mixed_companies/search` endpoints
- Requires Apollo Basic plan ($49/mo) for API access
- Full contact details (email, phone) require Apollo credits to reveal

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

- [ ] Bulk research (CSV upload → 100 companies)
- [ ] Saved research templates
- [ ] Competitor tracking over time
- [ ] AI chat follow-up on research
- [ ] PDF export

---

## Pricing Tiers (Current)

| Tier | Price | Searches | Features |
|------|-------|----------|----------|
| Free | $0 | 5 total | Full research |
| Pro | $24.99/mo | 25/mo | Full research + Credits option |
| Credit Pack | $10 one-time | +10 searches | For Pro users who need more |

### Future Tiers (Not Yet Built)
| Tier | Price | Searches | Features |
|------|-------|----------|----------|
| Team | $29/user/mo | 50/user/mo | Shared materials, team dashboard |
| Enterprise | Custom | Unlimited | SSO, API, SLA |

---

## Priority Timeline

| Timeframe | Phase | Goal |
|-----------|-------|------|
| ✅ Done | Phase 1 | Production launch with full v2 |
| ✅ Done | Phase 2 | Apollo contacts |
| ✅ Done | Phase 3 | Writing workflow |
| ✅ Done | Phase 3.5 | Microsoft OAuth for MSPs |
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
