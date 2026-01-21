# Auggie

AI-powered account research for sales teams. Enter a company URL, get deep research in minutes.

## What It Does

1. **Scrapes company websites** (Firecrawl) — homepage, about, careers, blog
2. **Detects technology stack** (Wappalyzer) — frameworks, databases, infrastructure
3. **Generates research document** (Claude AI) — tech stack analysis, pain points, MongoDB fit assessment, talking points

## Usage

1. Enter a company URL (e.g., `https://stripe.com`)
2. Click "Generate Research Document"
3. Wait 30-60 seconds for the research to complete
4. View, copy, or download your research document

## Project Structure

```
account_research/
├── main.py              # FastAPI app (routes, startup)
├── config.py            # Environment variable loading
├── models.py            # Pydantic data models
├── database.py          # SQLite operations
├── requirements.txt     # Python dependencies
├── .env                 # Your API keys (don't commit this!)
├── .env.example         # Template for API keys
├── research.db          # SQLite database (created on first run)
│
├── services/
│   ├── firecrawl.py     # Website scraping
│   ├── wappalyzer.py    # Technology detection
│   └── claude.py        # AI document generation
│
└── templates/
    ├── base.html        # Master template
    ├── index.html       # Home page (form)
    └── document.html    # Research document view
```

## Tech Stack

- **FastAPI** — Python web framework (async)
- **Firecrawl** — Web scraping API
- **Wappalyzer** — Technology detection
- **Anthropic Claude** — AI text generation
- **SQLite** — Local database
- **Jinja2** — HTML templating
- **Tailwind CSS** — Styling
