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

## Phase 2: Writing Workflow
**Status:** Next up

Add AI-powered outreach generation after research is created.

### Features
- [ ] "Write Outreach" button on research document
- [ ] Template types:
  - Cold Email
  - LinkedIn Message
  - Follow-up Email
  - Call Script
  - Custom prompt
- [ ] Uses research context + user materials
- [ ] Tone/style preferences
- [ ] Regenerate, copy, save drafts

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

CREATE TABLE outreach_templates (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(id),
    name TEXT,
    prompt TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### Files to Create/Modify
- [ ] services/writing.py - Outreach generation service
- [ ] templates/document.html - Add "Write Outreach" UI
- [ ] templates/outreach_modal.html - Draft editing modal
- [ ] main.py - Add /outreach endpoints
- [ ] database.py - Add outreach tables and functions

---

## Phase 3: Team Accounts
**Status:** Planned

Enable businesses to have multiple users under one organization.

- [ ] Org/team data model
- [ ] Invite team members
- [ ] Role-based access (Admin, Member, Viewer)
- [ ] Centralized billing (one bill per org)
- [ ] Shared materials library
- [ ] Usage dashboard (who researched what)

---

## Phase 4: Enterprise Auth & Security
**Status:** Planned

Required for enterprise sales.

- [ ] SSO (SAML/OIDC) - Okta, Azure AD, Google Workspace
- [ ] SCIM user provisioning
- [ ] Audit logs
- [ ] Data retention controls
- [ ] SOC 2 compliance prep

---

## Phase 5: Integrations
**Status:** Planned

Connect Auggie to sales team workflows.

- [ ] Salesforce integration (push research to accounts)
- [ ] HubSpot integration
- [ ] Slack notifications
- [ ] API access for customers
- [ ] Chrome extension
- [ ] Zapier/Make connectors

---

## Phase 6: Advanced Features
**Status:** Future

- [ ] Bulk research (CSV upload → 100 companies)
- [ ] Saved research templates
- [ ] Competitor tracking over time
- [ ] Contact enrichment (LinkedIn, Apollo)
- [ ] AI chat follow-up on research
- [ ] PDF export

---

## Pricing Tiers (Suggested)

| Tier | Price | Searches | Materials | Features |
|------|-------|----------|-----------|----------|
| Free | $0 | 5 total | 3 | Basic research |
| Pro | $9.99/mo | 25/mo | Unlimited | + Writing workflow |
| Team | $29/user/mo | 50/user/mo | Shared | + Team features |
| Enterprise | Custom | Unlimited | Shared | + SSO, API, SLA |

---

## Priority Timeline

| Timeframe | Phase | Goal |
|-----------|-------|------|
| This week | Phase 1 | Production launch, first paying users |
| Next 1-2 weeks | Phase 2 | Writing workflow |
| Month 2 | Phase 3 | Team accounts |
| Month 2-3 | Phase 5 | CRM integrations |
| Month 3+ | Phase 4 | Enterprise security |
