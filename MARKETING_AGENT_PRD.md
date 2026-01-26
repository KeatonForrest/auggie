# Marketing Content Agent - Product Requirements Document

## Overview

**Product Name:** Auggie Marketing Content Agent
**Version:** 1.0
**Author:** Claude
**Date:** January 2026

### Summary

The Marketing Content Agent is an automated system that generates, recycles, and schedules social media content for Auggie. It ingests existing marketing materials, extracts key themes and messages, and produces platform-specific content variants while maintaining brand voice consistency.

### Problem Statement

1. **Manual content creation is time-consuming** - Writing fresh social media content requires significant creative effort
2. **Inconsistent posting frequency** - Without automation, social presence becomes sporadic
3. **Underutilized existing content** - MARKETING.md, FAQ.md, and other docs contain valuable content that could be repurposed
4. **Brand voice drift** - Manual posting can lead to inconsistent messaging
5. **Cross-platform adaptation** - Each platform (Twitter, LinkedIn, etc.) requires different formatting and tone

### Goals

1. **Automate content generation** from existing marketing materials
2. **Maintain brand consistency** across all generated content
3. **Enable multi-platform publishing** with platform-specific optimization
4. **Create a sustainable content calendar** with minimal manual intervention
5. **Recycle high-performing themes** to maximize content ROI

---

## Target Users

### Primary User
- **Auggie founder/marketing owner** - Needs to maintain social presence without full-time marketing effort

### Secondary Users
- **Future marketing team members** - Will use the agent to scale content production
- **Content reviewers** - Will approve/edit generated content before publishing

---

## Functional Requirements

### FR1: Content Ingestion

| ID | Requirement | Priority |
|----|-------------|----------|
| FR1.1 | Read and parse MARKETING.md for brand voice, value props, one-liners | P0 |
| FR1.2 | Read and parse FAQ.md for educational content themes | P0 |
| FR1.3 | Read and parse ROADMAP.md for feature announcements | P1 |
| FR1.4 | Accept custom content snippets via API/CLI | P1 |
| FR1.5 | Track content freshness (last used date) | P2 |
| FR1.6 | Ingest user testimonials/feedback (future) | P2 |

### FR2: Content Generation

| ID | Requirement | Priority |
|----|-------------|----------|
| FR2.1 | Generate Twitter/X posts (≤280 characters) | P0 |
| FR2.2 | Generate LinkedIn posts (300-1300 characters) | P0 |
| FR2.3 | Generate blog post outlines | P1 |
| FR2.4 | Apply brand voice guidelines to all content | P0 |
| FR2.5 | Create 3-5 variants per source content | P0 |
| FR2.6 | Include appropriate hashtags per platform | P1 |
| FR2.7 | Generate hook/opening lines optimized for engagement | P1 |
| FR2.8 | Support different content types (value, engagement, promotional) | P0 |

### FR3: Content Calendar

| ID | Requirement | Priority |
|----|-------------|----------|
| FR3.1 | Generate weekly content calendar | P0 |
| FR3.2 | Balance content types (40% value, 30% engagement, 30% promotional) | P1 |
| FR3.3 | Suggest optimal posting times per platform | P2 |
| FR3.4 | Avoid duplicate/similar content within 30 days | P1 |
| FR3.5 | Export calendar to JSON/CSV | P1 |

### FR4: Content Recycling

| ID | Requirement | Priority |
|----|-------------|----------|
| FR4.1 | Identify evergreen content themes | P1 |
| FR4.2 | Generate fresh angles on proven topics | P1 |
| FR4.3 | Track which themes have been used recently | P1 |
| FR4.4 | Refresh seasonal/timely content | P2 |

### FR5: Output & Integration

| ID | Requirement | Priority |
|----|-------------|----------|
| FR5.1 | Output content to JSON format | P0 |
| FR5.2 | CLI interface for on-demand generation | P0 |
| FR5.3 | API endpoint for programmatic access | P1 |
| FR5.4 | Copy-to-clipboard functionality | P1 |
| FR5.5 | Direct posting to Twitter API (future) | P3 |
| FR5.6 | Direct posting to LinkedIn API (future) | P3 |
| FR5.7 | Buffer/Hootsuite integration (future) | P3 |

---

## Non-Functional Requirements

### NFR1: Performance
- Content generation should complete within 30 seconds
- Calendar generation should complete within 2 minutes
- Support batch generation of 50+ posts per run

### NFR2: Quality
- Generated content must pass brand voice validation
- No hallucinated features or incorrect pricing
- Proper grammar and formatting

### NFR3: Reliability
- Graceful degradation if AI service unavailable
- Retry logic for API failures
- Content validation before output

### NFR4: Maintainability
- Modular architecture for easy platform additions
- Configurable prompts and templates
- Comprehensive logging

---

## Content Types & Templates

### Type 1: Value Posts (Educational)
**Purpose:** Provide value, establish authority
**Frequency:** 3x per week
**Sources:** FAQ.md, pain points, tips

```
Template Structure:
- Hook (problem statement or surprising fact)
- Value (insight, tip, or solution)
- CTA (soft - "What's your approach?")
```

**Example:**
```
The average SDR spends 40% of their time on research.

That's 2+ hours per day checking:
→ Company websites
→ LinkedIn profiles
→ News articles
→ Job postings

What if you could get all of that in 60 seconds?

That's exactly what Auggie does. [link]
```

### Type 2: Feature Highlights
**Purpose:** Showcase capabilities
**Frequency:** 1x per week
**Sources:** MARKETING.md features, ROADMAP.md updates

```
Template Structure:
- Feature name
- What it does (benefit-focused)
- Example or result
- CTA (try it)
```

**Example:**
```
Tech stack detection that actually works.

Auggie doesn't guess what technologies a company uses - it scans their actual website code.

→ Frameworks
→ Databases
→ Analytics tools
→ Infrastructure

Know if they're running React or Vue before you get on the call.
```

### Type 3: Social Proof
**Purpose:** Build trust, show traction
**Frequency:** 1x per week
**Sources:** Testimonials, metrics, user stories

```
Template Structure:
- Quote or metric
- Context
- Credibility marker
```

### Type 4: Behind-the-Scenes
**Purpose:** Build connection, indie hacker appeal
**Frequency:** 1x per week
**Sources:** Technical decisions, build journey

```
Template Structure:
- Personal insight or decision
- Why it matters
- Lesson or takeaway
```

**Example:**
```
Why I chose FastAPI over Django for Auggie:

1. Async by default (critical for scraping 10+ pages)
2. Automatic OpenAPI docs
3. Pydantic validation built-in
4. Less magic, more explicit

5,500 lines of Python. Ships fast. Runs fast.
```

### Type 5: Engagement Posts
**Purpose:** Drive interaction, algorithm boost
**Frequency:** 2x per week
**Sources:** Industry debates, questions, polls

```
Template Structure:
- Question or hot take
- Context (optional)
- Invitation to respond
```

**Example:**
```
Hot take: ZoomInfo is a $15K/year contact database.

Most sales teams don't need a database. They need research done for them.

Agree or disagree?
```

---

## Platform-Specific Guidelines

### Twitter/X
- **Character limit:** 280
- **Optimal length:** 200-280 characters
- **Hashtags:** 1-2 max, at end
- **Style:** Punchy, line breaks, emojis sparingly
- **Best times:** 8-10am, 12-1pm, 5-6pm EST

### LinkedIn
- **Character limit:** 3000 (optimal 300-1300)
- **Style:** Professional, storytelling, longer form
- **Hashtags:** 3-5, at end
- **Format:** Hook line, body with line breaks, CTA
- **Best times:** Tuesday-Thursday, 7-8am, 12pm, 5-6pm

### Blog/Long-form
- **Length:** 800-1500 words
- **Structure:** H2 sections, bullet points, examples
- **SEO:** Target keywords, meta description
- **CTA:** Newsletter signup, product trial

---

## Data Model

### ContentSource
```python
class ContentSource:
    id: str
    source_file: str          # e.g., "MARKETING.md"
    content_type: str         # e.g., "value_prop", "feature", "faq"
    raw_content: str
    extracted_themes: list[str]
    last_used: datetime | None
    use_count: int
```

### GeneratedContent
```python
class GeneratedContent:
    id: str
    source_id: str
    platform: str             # "twitter", "linkedin", "blog"
    content_type: str         # "value", "feature", "engagement", etc.
    content: str
    hashtags: list[str]
    generated_at: datetime
    scheduled_for: datetime | None
    status: str               # "draft", "approved", "published"
    engagement_metrics: dict | None
```

### ContentCalendar
```python
class ContentCalendar:
    id: str
    week_start: date
    posts: list[GeneratedContent]
    platform_breakdown: dict  # {"twitter": 5, "linkedin": 3}
    type_breakdown: dict      # {"value": 3, "engagement": 2, ...}
```

---

## AI Prompt Architecture

### System Prompt (Brand Voice)
```
You are a content writer for Auggie, an AI-powered account research tool for sales teams.

Brand Voice Guidelines:
- Professional but approachable
- Confident but not arrogant
- Technical but accessible
- Specific over buzzwordy
- Benefit-focused and outcome-oriented

We say: "Research in 60 seconds", "Personalized talking points"
We don't say: "Revolutionary AI", "10x your sales", "The best tool ever"

Product facts:
- Price: $24.99/month for 25 researches
- Speed: 60 seconds per research
- Founded: Indie hacker, no VC funding
- Tech: 5,500 lines of Python, FastAPI, Claude AI
```

### Generation Prompt Template
```
Generate {count} {platform} posts about {topic}.

Content type: {content_type}
Source material: {source_content}

Requirements:
- {platform_specific_requirements}
- Include a hook that grabs attention
- End with appropriate CTA
- Stay within character limits
- Maintain brand voice

Output as JSON array with fields: content, hashtags, hook_type
```

---

## Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Content generation success rate | >95% | Posts that pass validation |
| Brand voice consistency | >90% | Manual audit of 20 posts/month |
| Time saved vs manual | >80% | Hours saved per week |
| Content variety score | >0.7 | Unique themes per week / total posts |
| Calendar completion rate | 100% | Posts generated for all scheduled slots |

---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| AI generates incorrect product info | High | Validate against source docs, human review |
| Brand voice inconsistency | Medium | Strong system prompts, periodic audits |
| Content fatigue (repetition) | Medium | Track themes, enforce variety rules |
| API rate limits/costs | Medium | Caching, batch processing, cost monitoring |
| Platform API changes | Low | Abstract platform layer, monitor changes |

---

## Out of Scope (v1)

- Direct social media posting (requires API approvals)
- A/B testing of content variations
- Engagement analytics dashboard
- User-generated content curation
- Video/image content generation
- Multi-language support
- Competitor content monitoring

---

## Dependencies

| Dependency | Purpose | Status |
|------------|---------|--------|
| Claude API | Content generation | Available |
| MARKETING.md | Source content | Exists |
| FAQ.md | Source content | Exists |
| ROADMAP.md | Source content | Exists |
| Twitter API | Direct posting (future) | Not configured |
| LinkedIn API | Direct posting (future) | Not configured |

---

## Approval

| Role | Name | Date | Status |
|------|------|------|--------|
| Product Owner | | | Pending |
| Engineering | | | Pending |
| Marketing | | | Pending |
