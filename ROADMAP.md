# Auggie - SaaS Roadmap

## Current State

Multi-user SaaS with Google OAuth, Postgres database, and Stripe billing. Users can sign up, complete onboarding with their product context, and generate personalized research documents.

**Completed Features:**
- [x] Web scraping via Firecrawl (15+ pages per research)
- [x] Technology detection via Wappalyzer (main site + app subdomains)
- [x] AI research generation via Claude (personalized to user's product)
- [x] Web UI for input and viewing documents
- [x] Markdown export
- [x] Google OAuth authentication
- [x] PostgreSQL database (Railway)
- [x] User onboarding (company name, product context, industry)
- [x] User-scoped documents
- [x] Usage tracking (searches per month)
- [x] Stripe subscription ($18/mo for 50 searches)

---

## Phase 1: Prompt Engineering

### 1.1 Research Quality
- [x] Review and tune Claude prompts for better output
- [x] Improve company summary extraction
- [x] Better tech stack analysis and relevance scoring
- [x] More actionable sales angles and talking points
- [x] Reduce generic/filler content

### 1.2 Product Fit Analysis
- [ ] Better mapping of prospect needs to user's product
- [ ] Industry-specific insights
- [ ] Competitive positioning suggestions
- [ ] Objection handling prep

### 1.3 Output Format
- [ ] Tune markdown structure for readability
- [ ] Add executive summary section
- [ ] Prioritize most valuable insights at top
- [ ] Consider different output lengths (quick vs. deep)

---

## Phase 2: Production Ready

### 2.1 Deployment
- [ ] Deploy to Railway
- [ ] Set up environment variables in production
- [ ] Configure custom domain
- [ ] Update Google OAuth redirect URIs for production
- [ ] Switch Stripe to live mode

### 2.2 Stripe Webhooks
- [ ] Set up webhook endpoint in Stripe Dashboard
- [ ] Add `STRIPE_WEBHOOK_SECRET` to production env
- [ ] Test subscription renewal flow
- [ ] Test cancellation flow

### 2.3 Error Handling & Monitoring
- [ ] Add Sentry for error tracking
- [ ] Add logging for production debugging
- [ ] Handle edge cases (scraping failures, API timeouts)

---

## Phase 3: Product Enhancements

### 3.1 Customization
- [ ] Custom product context profiles (save multiple products)
- [ ] Adjustable research depth (quick vs. deep)
- [ ] Custom prompt templates

### 3.2 News API Integration
- [ ] Integrate NewsAPI.org (or Serper.dev) for recent company news
- [ ] Search by company name + recent articles
- [ ] Feed news into Claude as "Recent News & Press" data source
- [ ] Surface funding announcements, product launches, exec changes as talking points

### 3.3 Additional Data Sources (Future)
- [ ] LinkedIn company pages (if API available)
- [ ] Crunchbase integration (funding, investors)
- [ ] G2/Capterra reviews

### 3.4 Export & Integrations
- [ ] PDF export (styled with WeasyPrint)
- [ ] Notion export
- [ ] Google Docs export
- [ ] Salesforce integration
- [ ] HubSpot integration

---

## Phase 4: Scale & Optimize

### 4.1 Performance
- [ ] Caching layer (Redis) for repeat domains
- [ ] Background job queue for research generation
- [ ] Webhook notifications when research complete

### 4.2 Analytics
- [ ] User activity tracking
- [ ] Popular companies researched
- [ ] Feature usage metrics

### 4.3 API Access (Future)
- [ ] Public API for programmatic access
- [ ] API key management
- [ ] Rate limiting

---

## Pricing

| Tier | Price | Searches |
|------|-------|----------|
| Free | $0 | 5 total (no reset) |
| Pro | $18/mo | 50/month (resets on payment) |

### Cost Structure

**Per-Research Costs:**
| Service | Cost | Notes |
|---------|------|-------|
| Firecrawl | ~$0.15-0.25 | 15 pages @ $0.01-0.02/page |
| Claude API | ~$0.02-0.05 | ~10k tokens |
| Wappalyzer | $0 | Open source, runs locally |
| **Total** | **~$0.20-0.30** | Per research |

**Monthly Infrastructure:**
| Service | Cost | Notes |
|---------|------|-------|
| Railway | $5-20 | Hosting + Postgres |
| Stripe | 2.9% + $0.30 | Per transaction |

**Break-Even Analysis:**
At $18/month for 50 searches:
- Cost per research: ~$0.25
- Max cost if fully used: $12.50
- Gross margin: ~$5.50 (31%)
- At 30% usage (15 searches): ~$14.25 margin (79%)

SDRs will use heavily, AEs won't - blended usage model makes this profitable.

---

## Launch Checklist

### Pre-Launch
- [x] Authentication working
- [x] Billing working
- [x] Usage limits enforced
- [ ] Production deployment stable
- [ ] Error monitoring (Sentry)

### Marketing
- [ ] Landing page with value prop
- [ ] Demo video
- [ ] 3 case study examples

### Legal
- [ ] Terms of Service
- [ ] Privacy Policy

---

## Open Questions (Resolved)

1. ~~**Auth**: Clerk vs direct OAuth~~ → **Google OAuth directly** (free, low friction)

2. ~~**Database**: MongoDB vs Postgres~~ → **PostgreSQL on Railway** (relational fits better)

3. ~~**Pricing**: $49 for 100 vs $18 for 50~~ → **$18/mo for 50 searches** (SDR/AE blended usage model)

---

*Last updated: January 2026*
