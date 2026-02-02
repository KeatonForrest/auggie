# Auggie

AI-powered account research for sales teams. Enter a company URL, get deep research in minutes.

**Live at [auggie.tools](https://auggie.tools)**

## What It Does

1. **Scrapes company websites** (Firecrawl) — homepage, about, careers, blog, job boards, investor relations
2. **Detects technology stack** (Wappalyzer) — frameworks, databases, infrastructure across domains
3. **Enriches with contacts** (BYOK — Apollo, PDL, Lusha, Cognism) — finds key decision makers
4. **Fetches recent news** (SerpAPI) — latest press and announcements
5. **Analyzes regulatory filings** (SEC EDGAR, Federal Register) — compliance deadlines, risk factors
6. **Generates research document** (Gemini 2.5 Flash) — company overview, pain/fit/timing scoring, talking points
7. **Writes outreach emails** (Mistral Medium 3.1) — personalized 3-email sequence tailored to the research

## Features

- **Google + Microsoft OAuth** — Sign in with Google or Microsoft
- **Onboarding flow** — Capture your product context for personalized research
- **Materials upload** — Upload sales collateral (PDFs, docs) for RAG-enhanced research
- **Stripe billing** — Consumption pricing: 10 free credits, then 10/$10, 100/$50, 500/$125
- **Team accounts** — Orgs, invites, shared credits, usage dashboard
- **Public API** — REST API with async jobs, webhooks, rate limiting, Python SDK
- **Chrome extension** — Research any company from their website
- **Pipeline automation** — Score → Enrich → Write Sequences → Push with automation rules
- **11 integrations** — Apollo, HubSpot, Salesforce, ZoomInfo, PDL, Lusha, Cognism, Instantly, Smartlead, Outreach, SalesLoft, Gong Engage
- **Notifications** — Slack and Microsoft Teams webhooks
- **Automation platforms** — Clay, Make, n8n, Zapier

## Project Structure

```
account_research/
├── main.py              # FastAPI app (routes, startup)
├── config.py            # Environment variables
├── models.py            # Pydantic data models
├── database.py          # PostgreSQL operations
├── billing.py           # Stripe subscription management
├── auth.py              # Google OAuth
├── requirements.txt     # Python dependencies
├── nixpacks.toml        # Railway build config
│
├── services/
│   ├── firecrawl.py     # Website scraping
│   ├── wappalyzer.py    # Technology detection
│   ├── claude.py        # AI research generation
│   ├── apollo.py        # Contact enrichment
│   ├── news.py          # News fetching (SerpAPI)
│   ├── writing.py       # Email sequence generation
│   ├── materials.py     # File upload handling
│   ├── parser.py        # Document parsing (PDF, DOCX, PPTX)
│   ├── chunking.py      # Text chunking for embeddings
│   ├── embeddings.py    # OpenAI embeddings
│   ├── retrieval.py     # Vector similarity search
│   └── storage.py       # Cloudflare R2 storage
│
└── templates/
    ├── base.html        # Master template
    ├── landing.html     # Marketing landing page
    ├── index.html       # Dashboard (research form)
    ├── document.html    # Research document view
    ├── onboarding.html  # Product context setup
    └── materials.html   # Materials management
```

## Tech Stack

- **FastAPI** — Python web framework (async)
- **PostgreSQL + pgvector** — Database with vector search (Neon)
- **Gemini 2.5 Flash** (via OpenRouter) — AI research generation
- **Mistral Medium 3.1** (via OpenRouter) — Email sequence writing
- **Firecrawl** — Web scraping API
- **Wappalyzer** — Technology detection
- **SerpAPI** — News search
- **SEC EDGAR / Federal Register** — Regulatory data (free)
- **OpenAI** — Embeddings for materials RAG
- **Cloudflare R2** — File storage
- **Stripe** — Billing (consumption pricing)
- **Google + Microsoft OAuth** — Authentication
- **Tailwind CSS** — Styling
- **Railway** — Hosting

## Environment Variables

See `.env.example` for required API keys and configuration.

## Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run the server
uvicorn main:app --reload
```

## Deployment

Deployed on Railway with automatic deploys from the `main` branch.
- Staging: `v2` branch
- Production: `main` branch
