# Auggie

AI-powered account research for sales teams. Enter a company URL, get deep research in minutes.

## What It Does

1. **Scrapes company websites** (Firecrawl) — homepage, about, careers, blog
2. **Detects technology stack** (Wappalyzer) — frameworks, databases, infrastructure
3. **Generates research document** (Claude AI) — tech stack analysis, pain points, MongoDB fit assessment, talking points

## Prerequisites

- Python 3.10+
- API keys for:
  - [Firecrawl](https://firecrawl.dev) — web scraping
  - [Anthropic](https://console.anthropic.com) — Claude AI

## Setup Instructions

### 1. Navigate to the project directory

```bash
cd /Users/keatonforrest/claudecodestuff/account_research
```

### 2. Create a virtual environment

```bash
python3 -m venv venv
```

### 3. Activate the virtual environment

```bash
source venv/bin/activate
```

You should see `(venv)` at the start of your terminal prompt.

### 4. Install dependencies

```bash
pip install -r requirements.txt
```

### 5. Set up your API keys

Copy the example environment file:

```bash
cp .env.example .env
```

Then edit `.env` with your actual API keys:

```bash
# Option 1: Using VS Code
code .env

# Option 2: Using nano (terminal editor)
nano .env
# (Edit the file, then Ctrl+O to save, Ctrl+X to exit)

# Option 3: Using TextEdit (Mac)
open -a TextEdit .env
```

Your `.env` file should look like this (with your real keys):

```
FIRECRAWL_API_KEY=fc-your-key-here
ANTHROPIC_API_KEY=sk-ant-your-key-here
```

### 6. Run the application

```bash
uvicorn main:app --reload
```

### 7. Open in browser

Go to: http://localhost:8000

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

## Stopping the Server

Press `Ctrl+C` in the terminal where the server is running.

## Restarting Later

Every time you want to run the app:

```bash
cd /Users/keatonforrest/claudecodestuff/account_research
source venv/bin/activate
uvicorn main:app --reload
```

## Troubleshooting

### "Address already in use" error

The port is occupied. Kill existing processes:

```bash
lsof -ti:8000 | xargs kill -9
```

Then restart with `uvicorn main:app --reload`

### Module not found errors

Make sure your virtual environment is activated:

```bash
source venv/bin/activate
```

### API errors

Check that your `.env` file has valid API keys and the services have credits remaining.

## Security Notes

- **Never commit `.env` to git** — it contains your API keys
- **Rotate keys** if accidentally exposed
- **Key rotation schedule:** Every 90 days for production, or immediately after exposure

## Tech Stack

- **FastAPI** — Python web framework (async)
- **Firecrawl** — Web scraping API
- **Wappalyzer** — Technology detection
- **Anthropic Claude** — AI text generation
- **SQLite** — Local database
- **Jinja2** — HTML templating
- **Tailwind CSS** — Styling
