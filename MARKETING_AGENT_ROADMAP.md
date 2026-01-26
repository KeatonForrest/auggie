# Marketing Content Agent - Roadmap

## Current Status: Planning Phase

The Marketing Content Agent will automate social media content generation by recycling existing marketing materials and generating platform-specific posts while maintaining brand voice consistency.

---

## Phase 1: Foundation
**Status:** Not Started
**Estimated Effort:** 1-2 weeks

Core infrastructure and content ingestion system.

### Goals
- Set up service module structure
- Implement content source parsing
- Create brand voice configuration

### Deliverables
- [ ] `services/marketing/` module directory
- [ ] `services/marketing/sources.py` - Content source reader
- [ ] `services/marketing/config.py` - Brand voice configuration
- [ ] `services/marketing/models.py` - Data models (ContentSource, GeneratedContent)
- [ ] Parse MARKETING.md and extract themes/messages
- [ ] Parse FAQ.md and extract educational content
- [ ] Parse ROADMAP.md and extract feature updates
- [ ] Unit tests for source parsing

### Technical Details
```
services/
  marketing/
    __init__.py
    sources.py      # ContentSourceReader class
    config.py       # BrandVoice, PlatformConfig
    models.py       # Pydantic models
```

### Success Criteria
- Can read all three source files
- Extracts at least 10 themes from MARKETING.md
- Extracts at least 5 FAQ topics
- All unit tests passing

---

## Phase 2: Content Generation Engine
**Status:** Not Started
**Estimated Effort:** 1-2 weeks

AI-powered content generation with brand voice enforcement.

### Goals
- Implement Claude-based content generation
- Create platform-specific adapters
- Build variant generation system

### Deliverables
- [ ] `services/marketing/generator.py` - Core generation logic
- [ ] `services/marketing/prompts.py` - Prompt templates
- [ ] `services/marketing/platforms.py` - Platform adapters (Twitter, LinkedIn)
- [ ] System prompt with brand voice guidelines
- [ ] Content type templates (value, feature, engagement, etc.)
- [ ] Variant generation (3-5 per source)
- [ ] Character limit enforcement
- [ ] Hashtag generation

### Technical Details
```python
# generator.py
class ContentGenerator:
    async def generate_post(
        self,
        source: ContentSource,
        platform: Platform,
        content_type: ContentType
    ) -> list[GeneratedContent]

    async def generate_variants(
        self,
        content: str,
        count: int = 3
    ) -> list[str]
```

### Success Criteria
- Generates valid Twitter posts (≤280 chars)
- Generates valid LinkedIn posts (300-1300 chars)
- Brand voice consistency >90% (manual review)
- Can produce 5 variants from single source

---

## Phase 3: Content Calendar
**Status:** Not Started
**Estimated Effort:** 1 week

Automated content planning and scheduling.

### Goals
- Build calendar generation system
- Implement content mix balancing
- Add duplication detection

### Deliverables
- [ ] `services/marketing/calendar.py` - Calendar generator
- [ ] Weekly content plan generation
- [ ] Content type balancing (40/30/30 rule)
- [ ] Duplicate/similarity detection
- [ ] JSON/CSV export functionality
- [ ] Content freshness tracking

### Technical Details
```python
# calendar.py
class ContentCalendar:
    async def generate_week(
        self,
        start_date: date,
        platforms: list[Platform]
    ) -> CalendarWeek

    def balance_content_types(
        self,
        posts: list[GeneratedContent]
    ) -> list[GeneratedContent]
```

### Content Mix (Weekly)
| Day | Twitter | LinkedIn |
|-----|---------|----------|
| Mon | Value post | Value post |
| Tue | Engagement | Feature highlight |
| Wed | Feature | Behind-the-scenes |
| Thu | Value post | Engagement |
| Fri | Behind-the-scenes | Social proof |
| Sat | Engagement | - |
| Sun | - | - |

### Success Criteria
- Generates 7-day content calendar
- Proper content type distribution
- No duplicate themes within 30 days
- Export works in JSON and CSV

---

## Phase 4: CLI Interface
**Status:** Not Started
**Estimated Effort:** 3-5 days

Command-line tool for content generation.

### Goals
- Create user-friendly CLI
- Enable on-demand content generation
- Support batch operations

### Deliverables
- [ ] `cli/marketing.py` - CLI entry point
- [ ] `generate` command - Single post generation
- [ ] `calendar` command - Weekly calendar generation
- [ ] `list-themes` command - Show available themes
- [ ] `preview` command - Preview without saving
- [ ] Output formatting (table, JSON, plain text)
- [ ] Copy-to-clipboard support

### Usage Examples
```bash
# Generate a single Twitter post
python -m cli.marketing generate --platform twitter --type value

# Generate weekly calendar
python -m cli.marketing calendar --week 2026-01-27

# List available themes
python -m cli.marketing list-themes

# Preview content without saving
python -m cli.marketing preview --count 5
```

### Success Criteria
- All commands working
- Help text for all options
- Clean output formatting
- Exit codes for scripting

---

## Phase 5: Content Recycling
**Status:** Not Started
**Estimated Effort:** 1 week

Intelligent content reuse and refresh system.

### Goals
- Track content usage history
- Identify evergreen themes
- Generate fresh angles on proven content

### Deliverables
- [ ] `services/marketing/recycler.py` - Recycling logic
- [ ] Content usage tracking (database/file)
- [ ] Evergreen content identification
- [ ] Theme refresh generation
- [ ] "Last used" tracking per theme
- [ ] Similarity scoring between posts

### Technical Details
```python
# recycler.py
class ContentRecycler:
    async def get_recyclable_themes(
        self,
        days_since_used: int = 30
    ) -> list[ContentSource]

    async def refresh_content(
        self,
        original: GeneratedContent,
        fresh_angle: bool = True
    ) -> GeneratedContent
```

### Success Criteria
- Tracks all generated content
- Identifies themes unused for 30+ days
- Generates meaningfully different variations
- No accidental duplicate posts

---

## Phase 6: API Endpoint
**Status:** Not Started
**Estimated Effort:** 3-5 days

REST API for programmatic access.

### Goals
- Expose generation capabilities via API
- Enable external tool integration
- Support async generation

### Deliverables
- [ ] `POST /api/marketing/generate` - Generate content
- [ ] `POST /api/marketing/calendar` - Generate calendar
- [ ] `GET /api/marketing/themes` - List themes
- [ ] `GET /api/marketing/history` - Generation history
- [ ] Authentication (API key or user session)
- [ ] Rate limiting

### API Design
```
POST /api/marketing/generate
{
    "platform": "twitter",
    "content_type": "value",
    "theme": "speed",  // optional
    "count": 3
}

Response:
{
    "posts": [
        {
            "content": "...",
            "hashtags": ["#sales", "#productivity"],
            "platform": "twitter",
            "character_count": 245
        }
    ]
}
```

### Success Criteria
- All endpoints working
- Proper authentication
- Response time <5s
- Comprehensive error handling

---

## Phase 7: Direct Publishing (Future)
**Status:** Future Consideration
**Estimated Effort:** 2-3 weeks

Direct integration with social media platforms.

### Goals
- Post directly to Twitter/X
- Post directly to LinkedIn
- Schedule future posts

### Deliverables
- [ ] Twitter API integration (OAuth 2.0)
- [ ] LinkedIn API integration
- [ ] Post scheduling system
- [ ] Publishing queue
- [ ] Failure retry logic
- [ ] Engagement tracking (likes, comments)

### Prerequisites
- Twitter Developer Account (elevated access)
- LinkedIn Marketing API access
- OAuth app registration

### Notes
- Requires platform API approval process
- Rate limits apply
- Consider Buffer/Hootsuite integration as alternative

---

## Phase 8: Analytics Dashboard (Future)
**Status:** Future Consideration
**Estimated Effort:** 2-3 weeks

Track content performance and optimize.

### Goals
- Visualize content performance
- Identify best-performing themes
- A/B testing support

### Deliverables
- [ ] Dashboard UI (`templates/marketing_dashboard.html`)
- [ ] Engagement metrics tracking
- [ ] Theme performance analysis
- [ ] Best posting time analysis
- [ ] Content performance reports
- [ ] A/B test framework

---

## Priority Timeline

| Timeframe | Phase | Goal |
|-----------|-------|------|
| Week 1-2 | Phase 1 | Foundation - content ingestion |
| Week 2-3 | Phase 2 | Content generation engine |
| Week 4 | Phase 3 | Content calendar system |
| Week 4-5 | Phase 4 | CLI interface |
| Week 5-6 | Phase 5 | Content recycling |
| Week 6-7 | Phase 6 | API endpoint |
| Future | Phase 7 | Direct publishing |
| Future | Phase 8 | Analytics dashboard |

---

## Technology Stack

| Component | Technology | Reason |
|-----------|------------|--------|
| Content Generation | Claude Sonnet 4 | Fast, cost-effective for marketing copy |
| Data Models | Pydantic | Consistent with existing codebase |
| CLI Framework | Click or argparse | Simple, standard |
| Storage | JSON files (v1) → PostgreSQL (v2) | Start simple, scale later |
| API | FastAPI | Consistent with existing codebase |

---

## Cost Estimates

### Claude API Usage (Monthly)
| Operation | Tokens/Call | Calls/Month | Est. Cost |
|-----------|-------------|-------------|-----------|
| Generate post | ~500 | 200 | ~$1.50 |
| Generate calendar | ~2000 | 8 | ~$0.50 |
| Variant generation | ~1000 | 100 | ~$1.00 |
| **Total** | | | **~$3/month** |

*Based on Claude Sonnet 4 pricing*

---

## Success Metrics

| Metric | Phase 1-4 Target | Phase 5-8 Target |
|--------|------------------|------------------|
| Posts generated/week | 10+ | 20+ |
| Time saved (hours/week) | 3+ | 5+ |
| Brand voice consistency | >90% | >95% |
| Calendar completion | 100% | 100% |
| Content variety score | >0.7 | >0.8 |

---

## Risks & Mitigations

| Risk | Phase | Mitigation |
|------|-------|------------|
| AI generates wrong product info | 2 | Strict source validation, fact-checking prompts |
| Content sounds robotic | 2 | Strong brand voice prompts, human review |
| API costs exceed budget | 2+ | Caching, batch processing, usage monitoring |
| Platform API access denied | 7 | Use Buffer/Hootsuite as alternative |
| Duplicate content posted | 3, 5 | Similarity detection, usage tracking |

---

## Dependencies on Existing Codebase

| Dependency | File | Usage |
|------------|------|-------|
| Claude client | services/claude.py | Reuse existing client setup |
| Config patterns | config.py | Environment variable handling |
| Pydantic models | models.py | Model patterns and validation |
| FastAPI app | main.py | API endpoint registration |

---

## Open Questions

1. **Storage strategy:** JSON files for v1 or database from start?
2. **Review workflow:** Human approval before posting, or fully automated?
3. **Multi-account support:** One brand or future multi-tenant?
4. **Image generation:** Include AI-generated images (DALL-E) in future?
5. **Content approval UI:** Needed, or CLI-only for v1?
