# Auggie

AI-powered account research for sales teams. Enter a company URL, get deep research in minutes.

**Live at [auggie.tools](https://auggie.tools)**

## What It Does

1. **Scrapes company websites** (Firecrawl) — homepage, about, careers, blog, job boards, investor relations
2. **Detects technology stack** (Wappalyzer + custom fingerprinting) — frameworks, databases, infrastructure across domains
3. **Analyzes security posture** — DNS records (SPF, DKIM, DMARC), SSL/TLS certificates
4. **Enriches with contacts** (BYOK — Apollo, PDL, Lusha, Cognism, LeadMagic, ZoomInfo) — finds key decision makers
5. **Analyzes regulatory filings** (SEC EDGAR, Federal Register) — compliance deadlines, risk factors
6. **Generates research document** (Gemini 2.5 Flash via OpenRouter) — company overview, pain/fit/timing scoring, talking points
7. **Writes outreach emails** (Mistral Small Creative via OpenRouter) — personalized 3-email sequence tailored to the research
8. **Pushes to sales tools** — Instantly, Smartlead, Outreach, SalesLoft, Gong Engage

## Features

- **Google + Microsoft OAuth** — Sign in with either provider
- **Onboarding flow** — Capture your product context for personalized research
- **Context uploads** — Upload sales collateral (PDFs, docs, decks) for RAG-enhanced research and outreach
- **Bulk research** — Upload CSV/Excel of domains, score and analyze in batch with filtering
- **Watchlist** — Monitor companies with automated bi-weekly re-research
- **Automation rules** — Score-based triggers for enrichment, sequence writing, and pushing
- **Stripe billing** — Consumption pricing: 10 free credits, then 10/$10, 100/$50, 500/$100
- **Team accounts** — Orgs, invites, shared credits, usage dashboard
- **Public API** — REST API with async jobs, webhooks, rate limiting
- **Python SDK** — Official SDK in `sdk/`
- **Chrome extension** — Research any company from their website
- **Vanity URLs** — Shareable `/@org/doc-slug` links for research documents
- **OG images** — Dynamic Open Graph images for link previews
- **Platforms hub** — Guides for Clay, Make, n8n, Zapier
- **14+ integrations** — Apollo, PDL, Lusha, Cognism, LeadMagic, ZoomInfo, HubSpot, Salesforce, Outreach, SalesLoft, Instantly, Smartlead, Gong Engage, Google Sheets
- **Notifications** — Slack and Microsoft Teams webhooks

## Project Structure

```
account_research/
├── main.py              # FastAPI app entry point
├── config.py            # Environment variables & settings
├── models.py            # Pydantic data models
├── auth.py              # Google + Microsoft OAuth
├── auth_cache.py        # Session caching
├── billing.py           # Stripe checkout & webhooks
├── worker.py            # Background job worker (PostgreSQL task queue)
├── requirements.txt     # Python dependencies
├── nixpacks.toml        # Railway build config
│
├── api/                 # Public REST API (prefix /v1)
│   ├── routes.py        # API endpoints
│   ├── webhooks.py      # Webhook endpoints
│   ├── auth.py          # Bearer token auth
│   ├── errors.py        # Structured error responses
│   ├── jobs.py          # Research job orchestration
│   ├── ratelimit.py     # Per-endpoint rate limiting
│   ├── tasks.py         # Tracked task creation
│   └── validation.py    # Request validation
│
├── db/                  # Database layer (asyncpg)
│   ├── _pool.py         # Connection pool
│   ├── _migrate.py      # Schema migrations
│   ├── users.py         # Users & orgs
│   ├── documents.py     # Research documents
│   ├── jobs.py          # Job tracking & credits
│   ├── lists.py         # Bulk research lists
│   ├── contacts.py      # Enriched contacts
│   ├── materials.py     # Uploaded context files
│   ├── integrations.py  # OAuth tokens & config
│   ├── api_keys.py      # API key management
│   ├── webhooks.py      # Webhook subscriptions
│   ├── watchlist.py     # Watched companies
│   ├── automation.py    # Automation rules
│   ├── task_queue.py    # Durable task queue
│   └── ...              # bulk, feedback, orgs, outreach, tech_signals
│
├── services/            # Business logic & external APIs
│   ├── claude.py        # Research generation (Gemini via OpenRouter)
│   ├── writing.py       # Email sequence generation (Mistral via OpenRouter)
│   ├── vision.py        # Screenshot extraction (Gemini via OpenRouter)
│   ├── firecrawl.py     # Website scraping
│   ├── wappalyzer.py    # Technology detection
│   ├── edgar.py         # SEC EDGAR filings
│   ├── federal_register.py  # Federal Register API
│   ├── dns_analyzer.py  # DNS record analysis
│   ├── ssl_analyzer.py  # SSL/TLS analysis
│   ├── pain_inference.py # Pain signal inference
│   ├── job_parser.py    # Job posting parsing
│   ├── reviews.py       # Company reviews
│   ├── embeddings.py    # OpenAI embeddings (materials RAG)
│   ├── retrieval.py     # Vector similarity search
│   ├── materials.py     # File upload & processing
│   ├── parser.py        # Document parsing (PDF, DOCX, PPTX)
│   ├── chunking.py      # Text chunking
│   ├── storage.py       # Cloudflare R2 storage
│   ├── og_image.py      # OG image generation
│   ├── notifications.py # Slack/Teams webhooks
│   ├── automation.py    # Automation rule evaluation
│   ├── apollo.py        # Apollo.io
│   ├── pdl.py           # People Data Labs
│   ├── lusha.py         # Lusha
│   ├── cognism.py       # Cognism
│   ├── leadmagic.py     # LeadMagic
│   ├── zoominfo.py      # ZoomInfo
│   ├── hubspot.py       # HubSpot
│   ├── salesforce.py    # Salesforce
│   ├── outreach.py      # Outreach
│   ├── salesloft.py     # SalesLoft
│   ├── smartlead.py     # Smartlead
│   ├── instantly.py     # Instantly
│   ├── gong_engage.py   # Gong Engage
│   ├── google_sheets.py # Google Sheets
│   └── techdetect/      # Custom tech fingerprinting engine
│
├── routes/              # Web UI route handlers
│   ├── research.py      # Research form & document views
│   ├── lists.py         # Bulk research management
│   ├── integrations.py  # OAuth flows & config
│   ├── settings.py      # User/org settings
│   ├── team.py          # Team management
│   ├── watchlist.py     # Watchlist UI
│   ├── platforms.py     # Platforms hub
│   └── admin.py         # Admin dashboard
│
├── templates/           # Jinja2 HTML templates (30+)
├── static/              # Images, fonts, favicon
├── migrations/          # Database migrations
├── tests/               # Test suite (44 test files)
├── sdk/                 # Python SDK package
├── chrome-extension/    # Browser extension
└── utils/               # Slug generation, helpers
```

## Tech Stack

- **FastAPI** — Async Python web framework
- **PostgreSQL + pgvector** — Database with vector search (Neon)
- **Gemini 2.5 Flash** (via OpenRouter) — AI research generation
- **Mistral Small Creative** (via OpenRouter) — Email sequence writing
- **Firecrawl** — Web scraping API
- **Wappalyzer** — Technology detection
- **SEC EDGAR / Federal Register** — Regulatory data (free APIs)
- **OpenAI** — Embeddings for context/materials RAG
- **Cloudflare R2** — File storage
- **Stripe** — Billing (one-time credit packs)
- **Google + Microsoft OAuth** — Authentication
- **Tailwind CSS** — Styling (via CDN)
- **Railway** — Hosting

## Environment Variables

See `.env.example` for required API keys and configuration.

## Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run the server
uvicorn main:app --reload

# Run background worker (separate terminal)
python3 worker.py
```

## Deployment

Deployed on Railway with automatic deploys from the `main` branch.
