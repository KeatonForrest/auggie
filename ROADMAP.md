# Auggie Product Roadmap

## Current Status: v2 on Staging
- Core research generation working
- Materials upload & RAG working
- Ready for production deployment

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
**Status:** Next up (tomorrow - build first)

Add key contacts to research output using Apollo.io API.

### Features
- [ ] Query Apollo API for contacts at target domain
- [ ] Filter by user's target personas (from onboarding)
- [ ] Display in research: name, title, email, LinkedIn URL
- [ ] Pro-tier only (adds API cost per search)

### Output Example
```
## Key Contacts

**Sarah Chen** - VP of Sales
sarah.chen@company.com | [LinkedIn](url)

**Mike Johnson** - Director of Sales Ops
mike.johnson@company.com | [LinkedIn](url)
```

### Files to Create/Modify
- [ ] services/apollo.py - Apollo API integration
- [ ] config.py - Add APOLLO_API_KEY
- [ ] main.py - Integrate into research flow
- [ ] services/claude.py - Add contacts to prompt/output
- [ ] models.py - Add Contact model

### Environment Variables
```
APOLLO_API_KEY=your_key
```

---

## Phase 3: Writing Workflow
**Status:** Next up (tomorrow - build second)

Add AI-powered outreach generation after research is created.

### Features
- [ ] "Write Outreach" button on research document
- [ ] Template types:
  - 3-Email Sequence (initial, follow-up, break-up)
  - LinkedIn Message
- [ ] Uses research context + materials + contacts
- [ ] Regenerate, copy functionality

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

## Pricing Tiers (Suggested)

| Tier | Price | Searches | Materials | Features |
|------|-------|----------|-----------|----------|
| Free | $0 | 5 total | 3 | Basic research |
| Pro | $9.99/mo | 25/mo | Unlimited | + Contacts, Writing workflow |
| Team | $29/user/mo | 50/user/mo | Shared | + Team features |
| Enterprise | Custom | Unlimited | Shared | + SSO, API, SLA |

---

## Priority Timeline

| Timeframe | Phase | Goal |
|-----------|-------|------|
| Tomorrow | Phase 2 + 3 | Apollo contacts + Writing workflow |
| Tomorrow | Phase 1 | Production launch with full v2 |
| Month 2 | Phase 4 | Team accounts |
| Month 2-3 | Phase 6 | CRM integrations |
| Month 3+ | Phase 5 | Enterprise security |
