# PRD: Auggie Public API

## Phase 6a: Public API Foundation

**Status:** Draft
**Author:** Keaton Forrest
**Last Updated:** January 28, 2026

---

## 1. Overview

### Vision

The Auggie API transforms Auggie from a standalone research tool into invisible intelligence infrastructure. Customers can integrate Auggie into their existing workflows (Clay, custom scripts, internal tools) without ever logging into auggie.tools.

### Strategic Importance

This is the foundation for enterprise. Without the API:
- No Clay integration (our primary enterprise use case)
- No bulk workflows
- No "intelligence layer" positioning
- We remain a point solution, not infrastructure

### One-Line Summary

> Enable any system to call Auggie and get back: pain score, research, and sequences.

---

## 2. Goals & Success Metrics

### Goals

| Goal | Description |
|------|-------------|
| G1 | Enable Clay integration (Auggie as enrichment column) |
| G2 | Support bulk/automated research workflows |
| G3 | Unlock enterprise sales with API access as premium feature |
| G4 | Maintain unit economics ($0.27-0.56 COGS per research) |

### Success Metrics

| Metric | Target | Timeframe |
|--------|--------|-----------|
| API customers | 10 paying | 90 days post-launch |
| API calls/month | 1,000 | 90 days post-launch |
| Revenue from API tier | $2,000 MRR | 90 days post-launch |
| Clay template published | Yes | 30 days post-launch |
| Uptime | 99.5% | Ongoing |
| P95 latency (research) | < 45 seconds | Ongoing |

---

## 3. User Stories & Use Cases

### Primary Persona: Clay Power User

**Sarah, Sales Ops Manager**

Sarah manages outbound for a 10-person sales team. She uses Clay to build prospect lists and enrich with multiple data sources. She wants to add "pain scoring" to prioritize which accounts reps should call first.

**Jobs to be Done:**
- Import list from Ocean.io into Clay
- Enrich each row with Auggie pain score
- Filter to high-pain accounts
- Generate personalized sequences
- Push to Instantly

### Secondary Persona: Technical Founder

**Mike, Founder/Head of Sales**

Mike is building a scrappy outbound motion. He writes Python scripts to automate his workflow. He wants to call Auggie programmatically to research accounts and generate sequences.

**Jobs to be Done:**
- Call API with a domain
- Get back pain score + key insights
- Generate sequence with contact context
- Pipe results into his CRM

### Tertiary Persona: Agency

**RevOps Agency**

An agency manages outbound for multiple clients. They want to white-label Auggie research into their own dashboards.

**Jobs to be Done:**
- API access with high volume
- Bulk research capabilities
- Custom branding on outputs (future)

---

## 4. Use Case Flows

### Use Case 1: Single Research (Synchronous)

```
Client                              Auggie API
  │                                     │
  │  POST /v1/research                  │
  │  { "url": "acme.com" }              │
  │ ───────────────────────────────────►│
  │                                     │
  │     (scraping, analysis: 20-40s)    │
  │                                     │
  │◄─────────────────────────────────── │
  │  {                                  │
  │    "id": "res_abc123",              │
  │    "status": "complete",            │
  │    "pain_score": 9,                 │
  │    "pain_summary": "...",           │
  │    "research": { ... },             │
  │    "created_at": "..."              │
  │  }                                  │
```

**Notes:**
- Synchronous for simplicity in v1
- Long timeout (60s) due to scraping
- Pain score synthesized from research

### Use Case 2: Single Research (Async with Webhook)

```
Client                              Auggie API                    Client Webhook
  │                                     │                              │
  │  POST /v1/research                  │                              │
  │  { "url": "acme.com",               │                              │
  │    "webhook": "https://..." }       │                              │
  │ ───────────────────────────────────►│                              │
  │                                     │                              │
  │◄─────────────────────────────────── │                              │
  │  { "id": "res_abc123",              │                              │
  │    "status": "processing" }         │                              │
  │                                     │                              │
  │                                     │  (scraping, analysis)        │
  │                                     │                              │
  │                                     │  POST webhook                │
  │                                     │ ────────────────────────────►│
  │                                     │  { "event": "research.complete",
  │                                     │    "research": { ... } }     │
```

**Notes:**
- Better for Clay (doesn't timeout)
- Webhook receives full payload
- Client can also poll GET /v1/research/{id}

### Use Case 3: Sequence Generation

```
Client                              Auggie API
  │                                     │
  │  POST /v1/research/{id}/sequence    │
  │  {                                  │
  │    "contact_name": "Mike Chen",     │
  │    "contact_title": "VP Eng",       │
  │    "contact_email": "mike@acme.com" │
  │  }                                  │
  │ ───────────────────────────────────►│
  │                                     │
  │◄─────────────────────────────────── │
  │  {                                  │
  │    "id": "seq_xyz789",              │
  │    "emails": [                      │
  │      { "subject": "...",            │
  │        "body": "..." },             │
  │      ...                            │
  │    ]                                │
  │  }                                  │
```

**Notes:**
- Requires existing research (uses research context)
- Contact info personalizes the sequence
- Fast (~5-10s, just LLM call)

### Use Case 4: Bulk Research (List)

```
Client                              Auggie API
  │                                     │
  │  POST /v1/lists                     │
  │  { "name": "Q1 Targets",            │
  │    "companies": ["acme.com", ...],  │
  │    "webhook": "https://..." }       │
  │ ───────────────────────────────────►│
  │                                     │
  │◄─────────────────────────────────── │
  │  { "id": "list_abc",                │
  │    "status": "processing",          │
  │    "total": 100 }                   │
  │                                     │
  │                                     │
  │  GET /v1/lists/{id}                 │
  │ ───────────────────────────────────►│
  │                                     │
  │◄─────────────────────────────────── │
  │  { "status": "processing",          │
  │    "completed": 47,                 │
  │    "total": 100 }                   │
  │                                     │
  │                                     │
  │  (webhook fires when complete)      │
  │                                     │
  │  GET /v1/lists/{id}/accounts        │
  │  ?min_pain_score=7                  │
  │ ───────────────────────────────────►│
  │                                     │
  │◄─────────────────────────────────── │
  │  { "accounts": [                    │
  │    { "domain": "acme.com",          │
  │      "pain_score": 9,               │
  │      "research_id": "res_..." },    │
  │    ...                              │
  │  ]}                                 │
```

**Notes:**
- Async by default (bulk takes time)
- Progress tracking via polling or webhooks
- Filter/sort accounts by pain score

---

## 5. API Design

### Base URL

```
Production: https://api.auggie.tools/v1
Staging:    https://api-staging.auggie.tools/v1
```

### Authentication

All requests require API key in header:

```
Authorization: Bearer sk_live_abc123...
```

API keys:
- Prefixed: `sk_live_` (production), `sk_test_` (staging)
- Scoped to user/org
- Revocable from dashboard
- Rate limited per key

### Endpoints

#### Research

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/v1/research` | Create new research |
| GET | `/v1/research/{id}` | Get research by ID |
| GET | `/v1/research` | List user's researches |

##### POST /v1/research

**Request:**
```json
{
  "url": "acme.com",
  "webhook_url": "https://your-app.com/webhook",  // optional
  "include_sequence": false,                       // optional, default false
  "contact": {                                     // optional, for sequence
    "name": "Mike Chen",
    "title": "VP Engineering",
    "email": "mike@acme.com"
  }
}
```

**Response (sync, no webhook):**
```json
{
  "id": "res_abc123",
  "status": "complete",
  "url": "acme.com",
  "pain_score": 9,
  "pain_summary": "Scaling pressure with PostgreSQL + 4-month open backend role + 3x growth announced",
  "pain_categories": {
    "scaling": 9,
    "technical_debt": 7,
    "competitive": 4,
    "organizational": 3
  },
  "research": {
    "company_overview": "...",
    "tech_stack": {
      "product": ["PostgreSQL", "Redis", "React"],
      "marketing": ["WordPress", "HubSpot"]
    },
    "hiring_signals": "...",
    "existential_data_points": "...",
    "product_fit": "...",
    "talking_points": [
      "Your /api subdomain shows response times averaging 340ms",
      "Backend Engineer role open since September",
      "..."
    ]
  },
  "sequence": null,  // null if include_sequence=false
  "created_at": "2026-01-28T12:00:00Z",
  "credits_used": 1
}
```

**Response (async, with webhook):**
```json
{
  "id": "res_abc123",
  "status": "processing",
  "url": "acme.com",
  "created_at": "2026-01-28T12:00:00Z"
}
```

##### GET /v1/research/{id}

**Response:** Same as POST response (full research object)

##### GET /v1/research

**Query params:**
- `limit` (default 20, max 100)
- `offset` (default 0)
- `min_pain_score` (filter)
- `status` (filter: processing, complete, failed)

**Response:**
```json
{
  "data": [ ... ],
  "total": 150,
  "limit": 20,
  "offset": 0
}
```

#### Sequences

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/v1/research/{id}/sequence` | Generate sequence for research |
| GET | `/v1/sequences/{id}` | Get sequence by ID |

##### POST /v1/research/{id}/sequence

**Request:**
```json
{
  "contact": {
    "name": "Mike Chen",
    "title": "VP Engineering",
    "email": "mike@acme.com"
  },
  "tone": "professional",           // optional: professional, casual, formal
  "sequence_length": 3              // optional: 2, 3, or 4 emails
}
```

**Response:**
```json
{
  "id": "seq_xyz789",
  "research_id": "res_abc123",
  "contact": {
    "name": "Mike Chen",
    "title": "VP Engineering",
    "email": "mike@acme.com"
  },
  "emails": [
    {
      "position": 1,
      "subject": "Quick question about your backend scaling",
      "body": "Mike,\n\nSaw your Backend Engineer role has been open since September...",
      "delay_days": 0
    },
    {
      "position": 2,
      "subject": "Re: Quick question about your backend scaling",
      "body": "Mike,\n\nFollowing up on my last note...",
      "delay_days": 3
    },
    {
      "position": 3,
      "subject": "Re: Quick question about your backend scaling",
      "body": "Mike,\n\nLast note from me...",
      "delay_days": 7
    }
  ],
  "created_at": "2026-01-28T12:05:00Z",
  "credits_used": 0  // sequences are free with research
}
```

#### Lists (Bulk)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/v1/lists` | Create new list |
| GET | `/v1/lists/{id}` | Get list status |
| GET | `/v1/lists/{id}/accounts` | Get accounts in list |
| POST | `/v1/lists/{id}/analyze` | Start/resume analysis |

##### POST /v1/lists

**Request:**
```json
{
  "name": "Q1 Enterprise Targets",
  "companies": [
    "acme.com",
    "globex.com",
    "initech.com"
  ],
  "webhook_url": "https://your-app.com/webhook",
  "auto_analyze": true  // start immediately, default true
}
```

**Response:**
```json
{
  "id": "list_abc123",
  "name": "Q1 Enterprise Targets",
  "status": "analyzing",
  "total": 3,
  "completed": 0,
  "failed": 0,
  "created_at": "2026-01-28T12:00:00Z"
}
```

##### GET /v1/lists/{id}/accounts

**Query params:**
- `min_pain_score` (filter)
- `max_pain_score` (filter)
- `status` (pending, complete, failed)
- `sort` (pain_score_desc, pain_score_asc, created_at)
- `limit`, `offset`

**Response:**
```json
{
  "data": [
    {
      "domain": "acme.com",
      "status": "complete",
      "pain_score": 9,
      "pain_summary": "...",
      "research_id": "res_abc123"
    },
    {
      "domain": "globex.com",
      "status": "complete",
      "pain_score": 3,
      "pain_summary": "...",
      "research_id": "res_def456"
    }
  ],
  "total": 3,
  "completed": 2,
  "failed": 0,
  "pending": 1
}
```

#### Webhooks

##### Webhook Payload

```json
{
  "event": "research.complete",
  "timestamp": "2026-01-28T12:01:00Z",
  "data": {
    "id": "res_abc123",
    "url": "acme.com",
    "pain_score": 9,
    "pain_summary": "...",
    "research": { ... }
  }
}
```

##### Event Types

| Event | Description |
|-------|-------------|
| `research.complete` | Single research finished |
| `research.failed` | Single research failed |
| `list.complete` | All accounts in list processed |
| `list.progress` | Batch progress update (every 10%) |
| `high_pain_detected` | Pain score >= 8 detected |

##### Webhook Security

- Include signature header: `X-Auggie-Signature: sha256=...`
- Computed: `HMAC-SHA256(webhook_secret, request_body)`
- Customers verify signature to ensure authenticity

#### Account / Usage

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v1/account` | Get account info + usage |
| GET | `/v1/account/api-keys` | List API keys |
| POST | `/v1/account/api-keys` | Create API key |
| DELETE | `/v1/account/api-keys/{id}` | Revoke API key |

##### GET /v1/account

**Response:**
```json
{
  "id": "user_abc123",
  "email": "mike@company.com",
  "plan": "pro",
  "usage": {
    "period_start": "2026-01-01",
    "period_end": "2026-01-31",
    "researches_used": 47,
    "researches_limit": 100,
    "researches_remaining": 53
  },
  "api_enabled": true
}
```

---

## 6. Pain Score Synthesis

### How Pain Score is Calculated

The pain score (1-10) is synthesized from the research document by Claude. It's not a simple formula - it's a judgment call based on:

**Signals that increase pain score:**

| Signal | Weight | Example |
|--------|--------|---------|
| Existential data point detected | +2-3 | "PostgreSQL + 3x growth + no DB hire" |
| Role open 4+ months | +1-2 | Hard problem, urgency |
| Competitor in stack | +1-2 | Displacement opportunity |
| Recent funding + hiring spike | +1-2 | Scaling pressure |
| Public performance issues | +2 | Reviews mention slowness |
| Layoffs + specific hiring | +1 | Critical function gap |

**Signals that decrease pain score:**

| Signal | Weight | Example |
|--------|--------|---------|
| No hiring signals | -2 | Not actively building |
| Recent successful migration | -2 | Already solved |
| Competitor recently adopted | -1 | Just switched, won't switch again |
| No product tech detected | -1 | Can't assess stack |

### Pain Categories

In addition to overall score, break down by category:

```json
{
  "pain_score": 9,
  "pain_categories": {
    "scaling": 9,          // Growth outpacing infrastructure
    "technical_debt": 7,   // Legacy systems, deprecated tech
    "cost": 4,             // Margin pressure, efficiency needs
    "competitive": 6,      // Market pressure, feature gaps
    "organizational": 3    // Team issues, process problems
  }
}
```

### Implementation

Add to Claude research prompt:

```
After completing the research, synthesize a pain score:

PAIN SCORE (1-10):
- 1-3: No urgency signals. Nurture list.
- 4-6: Some signals but not urgent. Worth reaching out.
- 7-8: Clear pain signals. Prioritize outreach.
- 9-10: Existential pain. Call today.

Provide:
1. Overall pain_score (integer 1-10)
2. pain_summary (one sentence explaining the score)
3. pain_categories (object with scaling, technical_debt, cost, competitive, organizational scores)

Base your score on DATA COCKTAIL combinations, not single signals.
A score of 9-10 requires multiple reinforcing signals.
```

---

## 7. Rate Limiting

### Limits by Tier

| Tier | Requests/min | Concurrent | Daily |
|------|--------------|------------|-------|
| Free | 5 | 1 | 10 |
| Pro | 30 | 5 | 500 |
| Team | 60 | 10 | 2000 |
| Enterprise | 120 | 25 | Unlimited |

### Rate Limit Headers

All responses include:

```
X-RateLimit-Limit: 30
X-RateLimit-Remaining: 27
X-RateLimit-Reset: 1706443200
```

### Rate Limit Response

When exceeded:

```
HTTP 429 Too Many Requests

{
  "error": {
    "code": "rate_limit_exceeded",
    "message": "Rate limit exceeded. Retry after 45 seconds.",
    "retry_after": 45
  }
}
```

---

## 8. Error Handling

### Error Response Format

```json
{
  "error": {
    "code": "invalid_url",
    "message": "The provided URL is not valid or unreachable",
    "param": "url",
    "doc_url": "https://docs.auggie.tools/errors#invalid_url"
  }
}
```

### Error Codes

| HTTP | Code | Description |
|------|------|-------------|
| 400 | `invalid_request` | Malformed request body |
| 400 | `invalid_url` | URL not valid or unreachable |
| 400 | `missing_param` | Required parameter missing |
| 401 | `invalid_api_key` | API key invalid or revoked |
| 401 | `missing_api_key` | No API key provided |
| 403 | `api_not_enabled` | API access not enabled for plan |
| 403 | `insufficient_credits` | Not enough credits |
| 404 | `not_found` | Resource not found |
| 429 | `rate_limit_exceeded` | Too many requests |
| 500 | `internal_error` | Server error |
| 503 | `service_unavailable` | Temporarily unavailable |

### Retry Logic Recommendations

Document for customers:

```python
# Recommended retry logic
import time
import random

def call_with_retry(func, max_retries=3):
    for attempt in range(max_retries):
        try:
            return func()
        except RateLimitError as e:
            time.sleep(e.retry_after)
        except ServerError:
            # Exponential backoff with jitter
            time.sleep((2 ** attempt) + random.uniform(0, 1))
    raise MaxRetriesExceeded()
```

---

## 9. Billing Integration

### Credit Consumption

| Action | Credits |
|--------|---------|
| Research (single) | 1 |
| Research (bulk, per account) | 1 |
| Sequence generation | 0 (included with research) |
| Get/List (read operations) | 0 |

### Plan Enforcement

```python
# Pseudo-code for credit check
async def create_research(user, request):
    # Check plan allows API
    if not user.plan.api_enabled:
        raise APINotEnabledError()

    # Check credits
    if user.credits_remaining < 1:
        raise InsufficientCreditsError()

    # Reserve credit
    await reserve_credit(user, amount=1)

    try:
        research = await perform_research(request.url)
        await confirm_credit(user, amount=1)
        return research
    except Exception:
        await release_credit(user, amount=1)
        raise
```

### Usage Tracking

New database table:

```sql
CREATE TABLE api_usage (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT REFERENCES users(id),
  api_key_id BIGINT REFERENCES api_keys(id),
  endpoint TEXT,
  method TEXT,
  credits_used INTEGER DEFAULT 0,
  response_status INTEGER,
  latency_ms INTEGER,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_api_usage_user_date ON api_usage(user_id, created_at);
```

### Stripe Integration

For subscription tiers with monthly limits:

```python
# At period start, reset usage
async def reset_monthly_usage(user):
    user.researches_used_this_period = 0
    await user.save()

# On research, increment
async def track_usage(user):
    user.researches_used_this_period += 1

    # Check if over limit
    if user.researches_used_this_period > user.plan.monthly_limit:
        # Either block or charge overage
        if user.plan.allows_overage:
            await charge_overage(user, amount=1)
        else:
            raise LimitExceededError()
```

---

## 10. Security

### API Key Security

- Keys are hashed in database (bcrypt)
- Only show full key once on creation
- Prefix visible for identification: `sk_live_abc...xyz`
- Keys scoped to user/org
- Audit log of key usage

### Data Security

- All traffic over HTTPS
- API keys transmitted in headers, never URLs
- Webhook payloads signed with HMAC
- Research data encrypted at rest
- No PII in logs

### API Key Table

```sql
CREATE TABLE api_keys (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT REFERENCES users(id),
  name TEXT,                          -- "Clay Integration"
  key_prefix TEXT,                    -- "sk_live_abc"
  key_hash TEXT,                      -- bcrypt hash
  scopes TEXT[],                      -- ['research:read', 'research:write']
  last_used_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  revoked_at TIMESTAMPTZ              -- null if active
);
```

---

## 11. Documentation

### Required Docs

| Doc | Description | Priority |
|-----|-------------|----------|
| Getting Started | Quick start guide | P0 |
| Authentication | API key setup | P0 |
| API Reference | Full endpoint docs | P0 |
| Webhooks | Setup and verification | P0 |
| Error Handling | Error codes and retry logic | P0 |
| Rate Limits | Limits by tier | P1 |
| SDKs | Python, Node examples | P1 |
| Clay Integration | Step-by-step Clay setup | P1 |
| Changelog | API version history | P2 |

### Documentation Platform

Options:
- Mintlify (modern, good DX)
- ReadMe (feature-rich)
- GitBook (simple)
- Custom (Docusaurus)

Recommendation: **Mintlify** - fast to set up, looks professional, good for API docs.

---

## 12. Implementation Plan

### Phase 6a-1: Core API (Week 1-2)

**Goal:** Basic research endpoint working

- [ ] API key generation + management
- [ ] Authentication middleware
- [ ] POST /v1/research (sync)
- [ ] GET /v1/research/{id}
- [ ] GET /v1/research (list)
- [ ] Pain score synthesis (update Claude prompt)
- [ ] Basic rate limiting
- [ ] Error handling
- [ ] Credit deduction

**Deliverable:** Can research a company via API, get pain score back

### Phase 6a-2: Sequences + Webhooks (Week 3)

**Goal:** Full single-research workflow

- [ ] POST /v1/research/{id}/sequence
- [ ] Webhook delivery system
- [ ] Webhook signature verification
- [ ] Async research option
- [ ] GET /v1/account (usage)

**Deliverable:** Can trigger research, get webhook, generate sequence

### Phase 6a-3: Bulk/Lists (Week 4)

**Goal:** Bulk workflow support

- [ ] POST /v1/lists
- [ ] GET /v1/lists/{id}
- [ ] GET /v1/lists/{id}/accounts
- [ ] Background job processing
- [ ] Progress webhooks

**Deliverable:** Can upload list, get all pain scores, filter by score

### Phase 6a-4: Polish + Docs (Week 5)

**Goal:** Production ready

- [ ] API documentation (Mintlify)
- [ ] Python SDK (basic)
- [ ] Clay integration guide
- [ ] Dashboard: API key management UI
- [ ] Dashboard: Usage tracking UI
- [ ] Billing integration (Stripe metered)

**Deliverable:** Customers can self-serve API access

---

## 13. Database Changes

### New Tables

```sql
-- API Keys
CREATE TABLE api_keys (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  key_prefix TEXT NOT NULL,           -- visible identifier
  key_hash TEXT NOT NULL,             -- bcrypt hash of full key
  scopes TEXT[] DEFAULT '{}',
  rate_limit_tier TEXT DEFAULT 'default',
  last_used_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  revoked_at TIMESTAMPTZ,

  CONSTRAINT api_keys_prefix_unique UNIQUE(key_prefix)
);

-- API Usage Logs
CREATE TABLE api_usage (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT REFERENCES users(id),
  api_key_id BIGINT REFERENCES api_keys(id),
  endpoint TEXT NOT NULL,
  method TEXT NOT NULL,
  request_id TEXT,                    -- for tracing
  credits_used INTEGER DEFAULT 0,
  response_status INTEGER,
  latency_ms INTEGER,
  ip_address INET,
  user_agent TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_api_usage_user_created ON api_usage(user_id, created_at);
CREATE INDEX idx_api_usage_key_created ON api_usage(api_key_id, created_at);

-- Webhooks
CREATE TABLE webhooks (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
  url TEXT NOT NULL,
  secret TEXT NOT NULL,               -- for signing
  events TEXT[] NOT NULL,             -- which events to send
  active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Webhook Deliveries (for debugging)
CREATE TABLE webhook_deliveries (
  id BIGSERIAL PRIMARY KEY,
  webhook_id BIGINT REFERENCES webhooks(id),
  event_type TEXT NOT NULL,
  payload JSONB NOT NULL,
  response_status INTEGER,
  response_body TEXT,
  delivered_at TIMESTAMPTZ,
  attempts INTEGER DEFAULT 1,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Lists
CREATE TABLE lists (
  id TEXT PRIMARY KEY,                -- list_abc123
  user_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  status TEXT DEFAULT 'created',      -- created, analyzing, complete, failed
  total_accounts INTEGER DEFAULT 0,
  completed_accounts INTEGER DEFAULT 0,
  failed_accounts INTEGER DEFAULT 0,
  webhook_url TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  completed_at TIMESTAMPTZ
);

-- List Accounts
CREATE TABLE list_accounts (
  id BIGSERIAL PRIMARY KEY,
  list_id TEXT REFERENCES lists(id) ON DELETE CASCADE,
  domain TEXT NOT NULL,
  status TEXT DEFAULT 'pending',      -- pending, processing, complete, failed
  pain_score INTEGER,
  pain_summary TEXT,
  pain_categories JSONB,
  research_id BIGINT REFERENCES research_documents(id),
  error_message TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  completed_at TIMESTAMPTZ
);

CREATE INDEX idx_list_accounts_list_status ON list_accounts(list_id, status);
CREATE INDEX idx_list_accounts_pain ON list_accounts(list_id, pain_score DESC);
```

### Modifications to Existing Tables

```sql
-- Add to research_documents
ALTER TABLE research_documents ADD COLUMN pain_score INTEGER;
ALTER TABLE research_documents ADD COLUMN pain_summary TEXT;
ALTER TABLE research_documents ADD COLUMN pain_categories JSONB;
ALTER TABLE research_documents ADD COLUMN api_request_id TEXT;  -- for tracing
ALTER TABLE research_documents ADD COLUMN source TEXT DEFAULT 'web';  -- 'web' or 'api'

-- Add to users
ALTER TABLE users ADD COLUMN api_enabled BOOLEAN DEFAULT FALSE;
ALTER TABLE users ADD COLUMN api_rate_limit_tier TEXT DEFAULT 'default';
```

---

## 14. Files to Create/Modify

### New Files

| File | Description |
|------|-------------|
| `api/__init__.py` | API module init |
| `api/routes.py` | FastAPI router for /v1/* |
| `api/auth.py` | API key authentication |
| `api/rate_limit.py` | Rate limiting middleware |
| `api/schemas.py` | Pydantic models for API |
| `services/webhooks.py` | Webhook delivery service |
| `services/lists.py` | Bulk list processing |
| `services/pain_score.py` | Pain score extraction |

### Modified Files

| File | Changes |
|------|---------|
| `main.py` | Mount API router |
| `database.py` | New tables, queries |
| `services/claude.py` | Add pain score to prompt |
| `models.py` | Add pain score fields |
| `config.py` | API-related settings |
| `billing.py` | API tier checks, metered usage |

---

## 15. Dependencies

### External

| Dependency | Purpose | Risk |
|------------|---------|------|
| Stripe | Metered billing | Low - already integrated |
| Background jobs | Async processing | Medium - need to add (Celery, or async tasks) |
| Redis | Rate limiting, job queue | Medium - new infrastructure |

### Internal

| Dependency | Purpose | Status |
|------------|---------|--------|
| Research generation | Core functionality | Done |
| Sequence generation | Core functionality | Done |
| User auth | Account management | Done |
| Billing | Credit management | Done |

---

## 16. Risks & Mitigations

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Long research times cause timeouts | API unusable | High | Webhook-based async flow |
| Abuse/scraping via API | Cost overrun | Medium | Rate limiting, monitoring |
| Pain score inconsistency | Poor prioritization | Medium | Prompt engineering, validation |
| Webhook delivery failures | Data loss | Medium | Retry logic, delivery logs |
| API versioning complexity | Maintenance burden | Low | Start simple, v1 prefix |

---

## 17. Success Criteria

### Launch Criteria (MVP)

- [ ] Can create research via API
- [ ] Pain score returned with research
- [ ] Sequences generated via API
- [ ] Webhooks delivered reliably
- [ ] API keys managed in dashboard
- [ ] Usage tracked and displayed
- [ ] Documentation published
- [ ] Clay integration tested end-to-end

### Post-Launch Criteria (30 days)

- [ ] 5+ customers using API
- [ ] 500+ API researches completed
- [ ] < 1% error rate
- [ ] P95 latency < 45 seconds
- [ ] Zero security incidents

---

## 18. Open Questions

| Question | Options | Decision |
|----------|---------|----------|
| Sync vs async default? | Sync simple, async scalable | TBD |
| Webhook retry policy? | 3x, 5x, exponential? | TBD |
| SDK priority? | Python first, then Node? | TBD |
| List size limit? | 100, 500, 1000? | TBD |
| Pain score in free tier? | Yes/No | TBD |

---

## Appendix A: Clay Integration Guide (Draft)

### Step 1: Get API Key

1. Log into auggie.tools
2. Go to Settings → API
3. Click "Create API Key"
4. Copy the key (you won't see it again)

### Step 2: Add Auggie to Clay

1. In Clay, open your table
2. Click "Add Enrichment"
3. Select "HTTP API"
4. Configure:
   - URL: `https://api.auggie.tools/v1/research`
   - Method: POST
   - Headers: `Authorization: Bearer YOUR_API_KEY`
   - Body: `{ "url": "{{company_domain}}" }`

### Step 3: Map Response

Map these fields to columns:
- `pain_score` → Pain Score
- `pain_summary` → Why
- `research.talking_points[0]` → Talking Point 1

### Step 4: Filter and Prioritize

Add a filter: `Pain Score >= 7`

Your high-pain accounts are now at the top.

---

## Appendix B: Python SDK (Draft)

```python
# Installation
# pip install auggie

from auggie import Auggie

client = Auggie(api_key="sk_live_...")

# Single research
research = client.research.create(url="acme.com")
print(research.pain_score)  # 9
print(research.pain_summary)  # "Scaling pressure..."

# Generate sequence
sequence = client.sequences.create(
    research_id=research.id,
    contact={
        "name": "Mike Chen",
        "title": "VP Engineering",
        "email": "mike@acme.com"
    }
)
print(sequence.emails[0].subject)

# Bulk list
list = client.lists.create(
    name="Q1 Targets",
    companies=["acme.com", "globex.com", "initech.com"]
)

# Wait for completion
list = client.lists.wait(list.id)

# Get high-pain accounts
accounts = client.lists.accounts(
    list.id,
    min_pain_score=7
)
for account in accounts:
    print(f"{account.domain}: {account.pain_score}")
```
