# Auggie

AI-powered account research for sales teams. Enter a company URL, get deep research in minutes.

**Live at [auggie.tools](https://auggie.tools)**

## What It Does

1. **Scrapes company websites** (Firecrawl) — homepage, about, careers, blog, job boards, investor relations
2. **Detects technology stack** (Wappalyzer) — frameworks, databases, infrastructure across domains
3. **Enriches with contacts** (Apollo.io) — finds key decision makers matching your target personas
4. **Fetches recent news** (SerpAPI) — latest press and announcements
5. **Generates research document** (Claude Opus) — company overview, tech analysis, pain points, product fit, talking points
6. **Writes outreach emails** (Claude Sonnet) — 3-email sequence tailored to the research

## Features

- **Google OAuth** — Sign in with Google
- **Onboarding flow** — Capture your product context for personalized research
- **Materials upload** — Upload sales collateral (PDFs, docs) for RAG-enhanced research
- **Stripe billing** — $24.99/month for 25 searches, bonus credit packs available
- **Export options** — Markdown download, copy to clipboard

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
- **Claude Opus 4** — AI research generation
- **Claude Sonnet 4** — Email sequence writing
- **Firecrawl** — Web scraping API
- **Wappalyzer** — Technology detection
- **Apollo.io** — Contact enrichment
- **SerpAPI** — News search
- **OpenAI** — Embeddings for materials
- **Cloudflare R2** — File storage
- **Stripe** — Billing and subscriptions
- **Google OAuth** — Authentication
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
