# Auggie — AI-Powered Account Research

## Overview
B2B account research tool for sales teams. Enter a company URL, get a deep research document with pain/fit/timing scoring, contact enrichment, and personalized outreach sequences. Live at auggie.tools.

## Stack
- **Framework:** FastAPI (async Python 3.10)
- **Database:** Neon Postgres + pgvector (asyncpg, 25 tables, 60+ indexes)
- **LLM:** Gemini 2.5 Flash (research), Mistral Small Creative (writing) — both via OpenRouter
- **Web Research:** Perplexity Sonar API (4 seller-shaped queries per report)
- **Scraping:** Firecrawl API (homepage + job boards + sitemap)
- **Storage:** Cloudflare R2 (materials uploads)
- **Payments:** Stripe (consumption credit packs)
- **Auth:** Google + Microsoft OAuth
- **Hosting:** Railway (auto-deploy from `main`)
- **Templates:** Jinja2 + Tailwind CSS (CDN)

## Key Files
| File | Purpose |
|------|---------|
| `main.py` | FastAPI app, middleware, error handlers |
| `config.py` | Pydantic settings from .env |
| `models.py` | Pydantic data models (`InfrastructureSignals`, `SignalBundle`, `ScrapedContent`, etc.) |
| `worker.py` | Background job worker (Postgres task queue, started from main.py lifespan) |
| `services/claude.py` | Research generation (Gemini via OpenRouter — misnamed) |
| `services/writing/` | Email/LinkedIn sequence generation (package: service.py, email.py, linkedin_*.py, types.py) |
| `services/firecrawl.py` | Website scraping (homepage + 3 job boards + free sitemap) |
| `services/perplexity.py` | Seller-shaped Perplexity web research (4 queries, 24h cache) |
| `services/tech_detection.py` | App subdomain/path discovery + Wappalyzer fingerprinting |
| `services/infrastructure_signals.py` | DNS + SSL + security headers + robots.txt (collapsed into one step) |
| `services/pain_inference.py` | Deterministic pain signal scoring (16+ rules, seller-category boosting) |
| `services/embeddings.py` | OpenAI embeddings for materials RAG |
| `services/job_parser.py` | Job posting parsing (tech mentions, role types, seniority) |
| `api/jobs.py` | Research pipeline orchestration |
| `db/` | All database access (one file per domain, asyncpg) |
| `api/` | Public REST API (v1 prefix) |
| `routes/` | Web UI route handlers |
| `sdk/` | Official Python SDK |

## Research Pipeline
```
1. Scrape (Firecrawl — homepage + job boards + sitemap, ~4 credits)
2. Parallel analysis:
   a) App domain tech detection (6 subdomains + 4 paths, deduped by redirect)
   b) Infrastructure signals (DNS + SSL + security headers + robots.txt → InfrastructureSignals)
   c) Perplexity (4 seller-shaped queries: domain + hiring + news + category-specific)
   d) Job parsing (tech mentions + role types + seniority)
3. Pain inference (consumes SignalBundle, seller-category boosting, compound rules)
4. Enrichment (EDGAR, Federal Register, seller materials RAG)
5. Generate (Gemini 2.5 Flash via OpenRouter — flat or tiered prompt)
```

## Running Locally
```bash
pip install -r requirements.txt
uvicorn main:app --reload        # API + web UI (worker starts automatically)
python3 -m pytest -q             # 40 test files, ~1500 tests
```

## Conventions
- Async everywhere (asyncpg, httpx, FastAPI)
- Type hints on all function signatures
- All DB access through `db/` module (never raw SQL in routes)
- Feature flags in config.py for gradual rollout
- OpenRouter for all LLM calls (never direct provider APIs)
- API error envelope: `{"error": {"code": "...", "message": "..."}}`
- Infrastructure flows through as `InfrastructureSignals` (single flat model, no legacy shims)
- Seller category shapes Perplexity queries, pain signal boosting, and evidence assembly

## Unit Economics
| Tier | Price | COGS/report | Margin |
|------|-------|-------------|--------|
| $10/10 | $1.00 | ~$0.07 | ~93% |
| $50/100 | $0.50 | ~$0.07 | ~86% |
| $100/500 | $0.20 | ~$0.07 | ~65% |

COGS breakdown: Firecrawl ~$0.004 (4 credits), Perplexity ~$0.01 (4 queries), Gemini ~$0.05, infrastructure signals ~free.

## Current Plans
- `.plan.md` — API/SDK hardening (Phase 1 done, Phases 2-4 remain)
