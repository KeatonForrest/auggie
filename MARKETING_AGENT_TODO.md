# Marketing Content Agent - Implementation TODO

## Overview

Actionable task list for building the Marketing Content Agent. Tasks are organized by phase and priority.

**Legend:**
- `[ ]` Not started
- `[~]` In progress
- `[x]` Complete
- `P0` Critical / Blocker
- `P1` High priority
- `P2` Medium priority
- `P3` Nice to have

---

## Phase 1: Foundation

### 1.1 Project Setup
- [ ] **P0** Create `services/marketing/` directory structure
- [ ] **P0** Create `services/marketing/__init__.py`
- [ ] **P0** Create `services/marketing/models.py` with Pydantic models
- [ ] **P0** Create `services/marketing/config.py` with configuration classes

### 1.2 Content Source Parsing
- [ ] **P0** Create `services/marketing/sources.py`
- [ ] **P0** Implement `ContentSourceReader` class
- [ ] **P0** Add method to parse MARKETING.md
  - [ ] Extract one-liners
  - [ ] Extract value propositions
  - [ ] Extract pain points
  - [ ] Extract social media copy examples
  - [ ] Extract competitor positioning
- [ ] **P0** Add method to parse FAQ.md
  - [ ] Extract questions and answers
  - [ ] Categorize by topic
- [ ] **P1** Add method to parse ROADMAP.md
  - [ ] Extract completed features
  - [ ] Extract upcoming features
- [ ] **P1** Implement theme extraction logic
- [ ] **P2** Add content freshness tracking

### 1.3 Brand Voice Configuration
- [ ] **P0** Define `BrandVoice` config class
  - [ ] Tone guidelines
  - [ ] Words to use
  - [ ] Words to avoid
  - [ ] Product facts (pricing, stats)
- [ ] **P0** Define `PlatformConfig` for each platform
  - [ ] Character limits
  - [ ] Hashtag rules
  - [ ] Formatting guidelines

### 1.4 Testing
- [ ] **P1** Create `tests/test_marketing_sources.py`
- [ ] **P1** Test MARKETING.md parsing
- [ ] **P1** Test FAQ.md parsing
- [ ] **P2** Test ROADMAP.md parsing
- [ ] **P2** Test theme extraction accuracy

---

## Phase 2: Content Generation Engine

### 2.1 Generator Core
- [ ] **P0** Create `services/marketing/generator.py`
- [ ] **P0** Implement `ContentGenerator` class
- [ ] **P0** Create async `generate_post()` method
- [ ] **P0** Create async `generate_variants()` method
- [ ] **P1** Add content validation (character limits, brand voice)

### 2.2 Prompts
- [ ] **P0** Create `services/marketing/prompts.py`
- [ ] **P0** Write system prompt with brand voice
- [ ] **P0** Write template for value posts
- [ ] **P0** Write template for feature highlights
- [ ] **P0** Write template for engagement posts
- [ ] **P1** Write template for behind-the-scenes
- [ ] **P1** Write template for social proof
- [ ] **P2** Write template for blog outlines

### 2.3 Platform Adapters
- [ ] **P0** Create `services/marketing/platforms.py`
- [ ] **P0** Implement `TwitterAdapter` class
  - [ ] Character counting (handle URLs, emojis)
  - [ ] Hashtag formatting
  - [ ] Thread support (future)
- [ ] **P0** Implement `LinkedInAdapter` class
  - [ ] Optimal length formatting
  - [ ] Hashtag positioning
  - [ ] Line break handling
- [ ] **P2** Implement `BlogAdapter` class
  - [ ] Markdown formatting
  - [ ] Section structure

### 2.4 Testing
- [ ] **P1** Create `tests/test_marketing_generator.py`
- [ ] **P1** Test Twitter character limits
- [ ] **P1** Test LinkedIn formatting
- [ ] **P2** Test variant uniqueness
- [ ] **P2** Test brand voice compliance

---

## Phase 3: Content Calendar

### 3.1 Calendar Generator
- [ ] **P0** Create `services/marketing/calendar.py`
- [ ] **P0** Implement `ContentCalendar` class
- [ ] **P0** Create `generate_week()` method
- [ ] **P1** Implement content type balancing
- [ ] **P1** Add duplicate detection
- [ ] **P2** Add optimal posting time suggestions

### 3.2 Export
- [ ] **P0** Implement JSON export
- [ ] **P1** Implement CSV export
- [ ] **P2** Implement markdown export (for review)

### 3.3 Testing
- [ ] **P1** Create `tests/test_marketing_calendar.py`
- [ ] **P1** Test content mix ratios
- [ ] **P2** Test duplicate detection

---

## Phase 4: CLI Interface

### 4.1 CLI Setup
- [ ] **P0** Create `cli/marketing.py`
- [ ] **P0** Set up Click/argparse framework
- [ ] **P0** Add `--help` documentation

### 4.2 Commands
- [ ] **P0** Implement `generate` command
  ```
  python -m cli.marketing generate --platform twitter --type value
  ```
- [ ] **P0** Implement `calendar` command
  ```
  python -m cli.marketing calendar --week 2026-01-27
  ```
- [ ] **P1** Implement `list-themes` command
- [ ] **P1** Implement `preview` command
- [ ] **P2** Add `--copy` flag for clipboard

### 4.3 Output Formatting
- [ ] **P1** Table format output
- [ ] **P1** JSON format output
- [ ] **P2** Plain text format output

### 4.4 Testing
- [ ] **P2** Create `tests/test_marketing_cli.py`
- [ ] **P2** Test all commands
- [ ] **P2** Test error handling

---

## Phase 5: Content Recycling

### 5.1 Usage Tracking
- [ ] **P0** Create `services/marketing/recycler.py`
- [ ] **P0** Implement content history storage (JSON file v1)
- [ ] **P1** Track last used date per theme
- [ ] **P1** Track usage count per theme

### 5.2 Recycling Logic
- [ ] **P1** Implement `get_recyclable_themes()` method
- [ ] **P1** Implement `refresh_content()` method
- [ ] **P2** Add similarity scoring
- [ ] **P2** Identify evergreen vs timely content

### 5.3 Testing
- [ ] **P2** Create `tests/test_marketing_recycler.py`
- [ ] **P2** Test theme identification
- [ ] **P2** Test refresh uniqueness

---

## Phase 6: API Endpoint

### 6.1 Endpoints
- [ ] **P0** Add routes to `main.py` or create `routes/marketing.py`
- [ ] **P0** Implement `POST /api/marketing/generate`
- [ ] **P1** Implement `POST /api/marketing/calendar`
- [ ] **P1** Implement `GET /api/marketing/themes`
- [ ] **P2** Implement `GET /api/marketing/history`

### 6.2 API Features
- [ ] **P1** Add authentication (session or API key)
- [ ] **P2** Add rate limiting
- [ ] **P2** Add request validation

### 6.3 Documentation
- [ ] **P1** Add OpenAPI schema documentation
- [ ] **P2** Create API usage examples

---

## Phase 7: Direct Publishing (Future)

### 7.1 Twitter Integration
- [ ] **P3** Register Twitter Developer account
- [ ] **P3** Implement OAuth 2.0 flow
- [ ] **P3** Create `services/marketing/publishers/twitter.py`
- [ ] **P3** Implement `publish_tweet()` method
- [ ] **P3** Add scheduling support

### 7.2 LinkedIn Integration
- [ ] **P3** Register LinkedIn Marketing API
- [ ] **P3** Implement OAuth flow
- [ ] **P3** Create `services/marketing/publishers/linkedin.py`
- [ ] **P3** Implement `publish_post()` method

### 7.3 Scheduling System
- [ ] **P3** Create publishing queue
- [ ] **P3** Implement scheduled job runner
- [ ] **P3** Add retry logic for failures

---

## Phase 8: Analytics Dashboard (Future)

### 8.1 Data Collection
- [ ] **P3** Create engagement tracking schema
- [ ] **P3** Implement metric fetching from platforms
- [ ] **P3** Store historical performance data

### 8.2 Dashboard UI
- [ ] **P3** Create `templates/marketing_dashboard.html`
- [ ] **P3** Build performance charts
- [ ] **P3** Add theme analysis view
- [ ] **P3** Create posting time heatmap

---

## Maintenance & Documentation

### Documentation
- [ ] **P1** Add docstrings to all public methods
- [ ] **P2** Create `docs/marketing_agent.md` usage guide
- [ ] **P2** Add examples to README section

### Code Quality
- [ ] **P1** Add type hints throughout
- [ ] **P2** Set up linting for new module
- [ ] **P2** Ensure consistent error handling

### Monitoring
- [ ] **P2** Add logging to generation process
- [ ] **P2** Track API costs per operation
- [ ] **P3** Set up cost alerts

---

## Quick Start Checklist

First 3 tasks to start building:

1. [ ] Create directory structure:
   ```bash
   mkdir -p services/marketing
   touch services/marketing/__init__.py
   touch services/marketing/models.py
   touch services/marketing/sources.py
   touch services/marketing/config.py
   ```

2. [ ] Define core models in `models.py`:
   - `ContentSource`
   - `GeneratedContent`
   - `ContentType` enum
   - `Platform` enum

3. [ ] Implement MARKETING.md parser in `sources.py`:
   - Read file
   - Extract sections
   - Parse into structured themes

---

## Dependencies to Install

```bash
# If not already installed
pip install click           # CLI framework (if not using argparse)
pip install pyperclip       # Clipboard support (optional)
```

---

## Environment Variables (Future)

```bash
# Add to .env when implementing publishing
TWITTER_API_KEY=
TWITTER_API_SECRET=
TWITTER_ACCESS_TOKEN=
TWITTER_ACCESS_SECRET=

LINKEDIN_CLIENT_ID=
LINKEDIN_CLIENT_SECRET=
```

---

## Notes

- Start with Phase 1-4 for MVP (content generation + CLI)
- Phase 5-6 adds persistence and API access
- Phase 7-8 are nice-to-haves for full automation
- Reuse existing `services/claude.py` patterns for AI calls
- Consider caching generated content to reduce API costs
