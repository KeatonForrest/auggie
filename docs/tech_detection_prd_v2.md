# Auggie Tech Stack Detection System — Revised PRD
## Integrated with Existing Codebase

**Version:** 2.0
**Date:** February 2026
**Status:** Draft
**Supersedes:** auggie_tech_detection_prd.md v1.0

---

## Executive Summary

This document outlines the requirements for upgrading Auggie's tech detection from a thin fingerprint matcher into a pain inference engine. Unlike the v1 PRD, this revision builds on the existing codebase — `services/techdetect/`, `services/wappalyzer.py`, `services/claude.py`, and the `technologies.json` fingerprint database (1,270 technologies, 68 categories) — rather than creating a parallel system.

**Core Principle (unchanged):** We detect signals that indicate pain potential, not just technology presence.

**What changed from v1:**
- No new `auggie/detection/` package. All work extends existing modules.
- No Redis dependency. Rate limiting stays in-process until multi-worker scaling demands it.
- Existing `technologies.json` fingerprints are retained and extended, not replaced by hand-written Python files.
- New analyzers (DNS, SSL) are added as `services/` modules wired into the existing pipeline at `api/jobs.py:40-43`.
- Pain inference rules are programmatic and feed into the existing Claude prompt, not replace it.

---

## Part 1: Current State (from audit)

### What works today

| Capability | Module | Status |
|-----------|--------|--------|
| HTML body pattern matching | `services/techdetect/detector.py:79-86` | Working |
| HTTP header pattern matching | `services/techdetect/detector.py:50-57` | Working |
| Script src pattern matching | `services/techdetect/detector.py:60-67` | Working |
| Meta tag pattern matching | `services/techdetect/detector.py:70-77` | Working |
| URL pattern matching | `services/techdetect/detector.py:41-47` | Working |
| Implied technology resolution (BFS) | `services/techdetect/detector.py:99-146` | Working |
| Subdomain probing (10 subdomains) | `services/wappalyzer.py:220-241` | Working |
| App path probing (12 paths) | `services/wappalyzer.py:243-272` | Working |
| robots.txt compliance | `services/wappalyzer.py:198-218` | Working |
| Rate limiting (semaphore + delay) | `services/wappalyzer.py:143-148` | Working |
| Job board scraping (Greenhouse/Lever/Ashby) | `services/firecrawl.py:115-168` | Working, but AI-parsed |
| 1,270 tech fingerprints, 68 categories | `services/data/technologies.json` | Working |

### What's broken or missing

| Gap | Impact | Priority |
|-----|--------|----------|
| JS global patterns (`js` key) not loaded or checked | Hundreds of technologies undetectable (React, Angular, analytics) | P0 |
| Cookie patterns (`cookies` key) not loaded or checked | CRM, e-commerce, session tools invisible | P1 |
| No DNS analysis | Cloud provider, email provider, CDN all invisible | P1 |
| No SSL/TLS certificate analysis | Cert posture, automation maturity invisible | P2 |
| No programmatic pain inference | Claude guesses pain from sparse signals; no structured rules | P1 |
| No structured job posting parsing | Tech extraction from jobs is inconsistent (Claude-only) | P2 |
| Tech stored as single TEXT blob (`research_documents.confirmed_tech_stack`) | Cannot query, combine, or track historically | P1 |
| `dom` patterns not loaded | Some technologies only detectable via DOM selectors | P3 |

---

## Part 2: Signal Categories & Detection Methods

### Tier 1: Zero Footprint (new)

#### 1.1 DNS Analysis — `services/dns_analyzer.py` (new file)

**What we detect:**
- Cloud provider from NS records (AWS Route53, Cloudflare, Azure DNS, GCP)
- Email provider from MX records (Google Workspace, Microsoft 365, custom)
- SPF/DKIM/DMARC from TXT records (email deliverability posture)
- Subdomain count from zone enumeration via certificate transparency logs (passive, not brute-force)

**Method:** Async DNS queries via `aiodns`. Standard public resolver queries — these are normal DNS lookups, not enumeration attacks.

**Pain signals:**
| Signal | Inference |
|--------|-----------|
| Mixed DNS providers (e.g., Route53 NS + Cloudflare MX) | Recent migration or M&A integration pain |
| No SPF or DKIM TXT records | Email deliverability problems |
| 10+ subdomains via CT logs | Sprawl/governance issues |
| MX pointing to custom server (not Google/Microsoft) | Self-hosted email = ops burden |

**Integration point:** Called in `_run_research_pipeline()` after Firecrawl scrape, before Claude generation. Results added to `tech_by_domain` dict under a `_dns` key, and formatted into the prompt as a new "## DNS & Infrastructure Signals" section.

#### 1.2 SSL/TLS Certificate Analysis — `services/ssl_analyzer.py` (new file)

**What we detect:**
- Certificate authority (Let's Encrypt = automation, DigiCert/Comodo = enterprise)
- Certificate expiry and renewal patterns
- SAN (Subject Alternative Names) revealing additional properties
- TLS version and cipher strength

**Method:** `ssl` + `asyncio` stdlib. Single connection to port 443.

**Pain signals:**
| Signal | Inference |
|--------|-----------|
| Cert expiring within 30 days + Let's Encrypt = OK; + DigiCert = possible ops gap | Manual renewal risk |
| Self-signed in production | Security posture concern |
| 20+ SANs | Infrastructure consolidation or sprawl |
| TLS 1.0/1.1 still enabled | Compliance risk (PCI DSS, etc.) |

**Integration point:** Same as DNS — called in pipeline, results formatted into prompt.

### Tier 2: Light-Touch Detection (existing, upgraded)

#### 2.1 Enable JS Global Detection — modify `services/techdetect/`

The existing `technologies.json` contains `js` properties for hundreds of technologies. Example:
```json
"React": { "js": {"React.version": ""}, ... }
```

These are currently **ignored** by `fingerprints.py` (not loaded) and `detector.py` (not checked).

**Change:** Since we don't execute JavaScript in-browser, we cannot check JS globals directly. However, we can:
1. Load `js` patterns and convert global names to **HTML regex patterns** where feasible (e.g., `window.React` or `__NEXT_DATA__` in inline scripts).
2. Add **inline script pattern matching** to `webpage.py` — currently we only extract `script[src]`, not inline script content.

**What this unlocks:**
- Next.js (`__NEXT_DATA__`), Nuxt (`__NUXT__`), Gatsby (`___gatsby`), Remix
- Analytics tools that initialize inline (`gtag()`, `analytics.track()`, `mixpanel.init()`)
- A/B testing tools (`optimizely`, `VWO`, `LaunchDarkly`)

**Files changed:** `services/techdetect/fingerprints.py`, `services/techdetect/detector.py`, `services/techdetect/webpage.py`

#### 2.2 Enable Cookie Detection — modify `services/techdetect/`

The existing `technologies.json` contains `cookies` properties. Example:
```json
"Shopify": { "cookies": {"_shopify_s": ""}, ... }
```

Currently ignored.

**Change:**
1. Add `cookie_patterns` field to `Technology` dataclass in `fingerprints.py`
2. Load `cookies` patterns from JSON
3. Pass `Set-Cookie` headers to `WebPage`, parse cookie names
4. Add cookie matching in `detector.py._check_technology()`

**What this unlocks:** Shopify, Magento, HubSpot, Salesforce, many A/B testing and session tools.

**Files changed:** `services/techdetect/fingerprints.py`, `services/techdetect/detector.py`, `services/techdetect/webpage.py`

#### 2.3 HTTP Header Analysis (existing, enhanced)

Headers are already fetched via `wappalyzer.py:123-131` and matched via `detector.py:50-57`. Enhancement:

**Add security header scoring.** After running the fingerprint matcher, separately score the presence/absence of:
- `Strict-Transport-Security`
- `Content-Security-Policy`
- `X-Frame-Options`
- `X-Content-Type-Options`
- `Referrer-Policy`
- `Permissions-Policy`

This produces a `security_posture_score` (0-100) that feeds into pain inference.

**File changed:** `services/wappalyzer.py` — add `_score_security_headers()` method.

#### 2.4 Robots.txt Signal Extraction (existing, enhanced)

robots.txt is already fetched and parsed for compliance (`wappalyzer.py:198-218`). Enhancement:

**Extract signals from disallowed paths:**
- `/api`, `/graphql` → API exists (integration opportunity)
- `/admin`, `/wp-admin` → CMS admin (WordPress etc.)
- `Crawl-delay` value → infrastructure strain indicator

**File changed:** `services/wappalyzer.py` — add `_extract_robots_signals()` method.

### Tier 3: Enrichment (existing, enhanced)

#### 3.1 Structured Job Posting Parser — `services/job_parser.py` (new file)

Currently job postings are scraped by Firecrawl (`services/firecrawl.py:115-168`) and passed as raw markdown to Claude. Claude extracts tech mentions inconsistently.

**Change:** Add a programmatic pre-parser that:
1. Regex-extracts technology names from job posting markdown against a curated keyword list
2. Counts mentions per technology
3. Identifies role types (DevOps, Data Engineer, Security, SRE, etc.)
4. Detects time-open signals ("posted 3 months ago", date parsing)
5. Produces structured `JobSignals` passed to both pain inference and Claude prompt

**Integration:** Called between Firecrawl scrape and Claude generation. Output injected into prompt as structured data alongside raw job text.

#### 3.2 Public Company Data (existing — no changes)

SEC EDGAR and news are already integrated via `services/collect.py:107-130`. No changes needed.

---

## Part 3: Ethical & Legal Guardrails

### Principles (same as v1, already partially implemented)

1. **Respect robots.txt** — Already implemented (`wappalyzer.py:198-218`). Extend to DNS/SSL analyzers (N/A for DNS; SSL is a standard TLS handshake).
2. **Rate limit aggressively** — Already implemented (`wappalyzer.py:143-148`, semaphore of 3 + 0.3s delay). DNS and SSL analyzers get their own semaphores.
3. **No authentication bypass** — Already implemented (403s are rejected as of recent changes).
4. **No form submission** — Not applicable to current code.
5. **Transparent User-Agent** — Already implemented: `"Mozilla/5.0 (compatible; AuggieBot/1.0)"`. Consider adding info URL.
6. **Data minimization** — Store signals, not raw HTML.

### What We Never Do (unchanged from v1)

- Spider or crawl beyond the homepage (Firecrawl handles multi-page with its own compliance)
- Execute JavaScript or render pages
- Submit forms or trigger server-side actions
- Attempt to bypass rate limiting
- Access authenticated/gated content
- Store PII discovered incidentally

### Rate Limiting Architecture

**Current:** In-process `asyncio.Semaphore(3)` in `WappalyzerService.__init__`. Sufficient for single-worker deployment.

**When to upgrade to Redis:** Only if we move to multi-worker (e.g., multiple Celery workers or k8s pods processing domains concurrently). Until then, in-process limiting is simpler and has no external dependency.

**Per-analyzer limits (in-process):**

| Analyzer | Concurrency | Delay | Rationale |
|----------|------------|-------|-----------|
| DNS | 10 | 0s | Lightweight, distributed across resolvers |
| SSL | 5 | 0.1s | Single TCP connection per domain |
| HTTP HEAD (existing) | 3 | 0.3s | Already implemented |
| HTML GET (via Firecrawl) | 1 | N/A | Firecrawl manages its own rate limiting |

---

## Part 4: Data Architecture

### New Models — `models.py` additions

```python
class TechSignal(BaseModel):
    """A single detected signal with provenance."""
    domain: str
    signal_type: str       # "analytics_tool", "cloud_provider", "security_header", etc.
    signal_value: str      # "Google Analytics 4", "AWS", "missing_csp"
    confidence: float      # 0.0 - 1.0
    detection_method: str  # "fingerprint_html", "dns_ns", "header_analysis", "job_parse"
    raw_evidence: str      # The pattern/record that matched
    category: str          # From technologies.json category or custom

class PainInference(BaseModel):
    """A programmatic pain inference from combined signals."""
    pain_category: str     # "identity_fragmentation", "scaling_pressure", "tech_debt"
    intensity: float       # 0.0 - 1.0
    signal_ids: list[str]  # References to contributing TechSignals
    rationale: str         # Human-readable explanation
    pvp_angle: str         # Suggested messaging hook
```

### Storage — new migration

```sql
-- New table: normalized tech signals per domain per research run
CREATE TABLE IF NOT EXISTS tech_signals (
    id BIGSERIAL PRIMARY KEY,
    document_id BIGINT REFERENCES research_documents(id) ON DELETE CASCADE,
    domain TEXT NOT NULL,
    signal_type TEXT NOT NULL,
    signal_value TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 1.0,
    detection_method TEXT NOT NULL,
    raw_evidence TEXT,
    category TEXT,
    detected_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_tech_signals_document ON tech_signals(document_id);
CREATE INDEX idx_tech_signals_domain ON tech_signals(domain);
CREATE INDEX idx_tech_signals_type ON tech_signals(signal_type);

-- New table: pain inferences per research run
CREATE TABLE IF NOT EXISTS pain_inferences (
    id BIGSERIAL PRIMARY KEY,
    document_id BIGINT REFERENCES research_documents(id) ON DELETE CASCADE,
    pain_category TEXT NOT NULL,
    intensity REAL NOT NULL,
    rationale TEXT,
    pvp_angle TEXT,
    contributing_signals JSONB,  -- array of tech_signal IDs
    detected_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_pain_inferences_document ON pain_inferences(document_id);
CREATE INDEX idx_pain_inferences_category ON pain_inferences(pain_category);
```

The existing `confirmed_tech_stack TEXT` column in `research_documents` remains for backward compatibility — Claude still writes it. The new tables provide queryable, structured data alongside it.

### No Redis (yet)

The v1 PRD specified Redis for rate limiting, robots.txt caching, and signal deduplication. This is unnecessary at current scale:
- Rate limiting: `asyncio.Semaphore` (already working)
- robots.txt caching: In-memory dict on `WappalyzerService` (already working at `wappalyzer.py:53`)
- Signal deduplication: Handled at insert time via `document_id` + `domain` + `signal_type` + `signal_value` uniqueness

Add Redis when (and only when) we need cross-process shared state.

---

## Part 5: Implementation Phases

### Phase 1: Unlock Existing Fingerprints (highest ROI)

**Goal:** Go from ~200 detectable technologies to ~800+ by enabling pattern types already defined in `technologies.json` but not loaded by the engine.

#### 1.1 Inline script extraction
**File:** `services/techdetect/webpage.py`

Currently `_parse_html()` only extracts `script[src]` (external scripts). Add extraction of inline `<script>` content for pattern matching.

```python
# Add to WebPage._parse_html():
self.inline_scripts = "\n".join(
    tag.string for tag in soup.find_all("script")
    if tag.string and not tag.get("src")
)
```

#### 1.2 JS-to-inline pattern conversion
**File:** `services/techdetect/fingerprints.py`

Load `js` entries from `technologies.json`. For each JS global pattern (e.g., `React.version`, `__NEXT_DATA__`, `gtag`), generate a regex that matches the global name appearing in inline script content. Add these as `inline_script_patterns` on the `Technology` dataclass.

Not all JS globals will appear in inline scripts — but many SPA frameworks and analytics tools initialize inline. This is a best-effort expansion, not full JS execution.

#### 1.3 Cookie pattern loading
**File:** `services/techdetect/fingerprints.py`

Load `cookies` entries. Add `cookie_patterns: tuple[tuple[str, PreparedPattern], ...]` to `Technology` dataclass.

#### 1.4 Cookie matching
**Files:** `services/techdetect/webpage.py`, `services/techdetect/detector.py`

- `WebPage`: Parse `Set-Cookie` headers into a `cookies: dict[str, str]` (name → value)
- `detector.py._check_technology()`: Add cookie pattern matching block after header matching

#### 1.5 Inline script matching
**File:** `services/techdetect/detector.py`

Add pattern matching against `webpage.inline_scripts` for inline script patterns, positioned between script src and HTML body checks (medium cost).

#### Deliverables:
- [ ] Inline script content extracted in `WebPage`
- [ ] `js` patterns converted to inline script regexes and loaded
- [ ] `cookies` patterns loaded and matched
- [ ] Tests for each new detection path
- [ ] Run against 10 known domains to validate coverage increase

#### Verification:
```bash
pytest tests/test_techdetect.py tests/test_wappalyzer.py -v
```

---

### Phase 2: DNS & SSL Analyzers

**Goal:** Add infrastructure signal detection that is currently completely absent.

#### 2.1 DNS Analyzer — `services/dns_analyzer.py` (new)

```python
class DNSAnalyzer:
    """Async DNS analysis for infrastructure signals."""

    async def analyze(self, domain: str) -> DNSProfile:
        """Returns nameservers, MX records, TXT records, inferred providers."""
        ...
```

**Implementation details:**
- Use `aiodns` for async resolution
- NS record → cloud provider mapping (AWS: `ns-*.awsdns-*`, Cloudflare: `*.ns.cloudflare.com`, GCP: `ns-cloud-*.googledomains.com`, Azure: `*.azure-dns.com`)
- MX record → email provider mapping (Google: `*.google.com`, Microsoft: `*.mail.protection.outlook.com`)
- TXT records → SPF/DKIM/DMARC presence check
- Semaphore of 10, no delay (DNS is lightweight and distributed)
- Handle NXDOMAIN, timeout, SERVFAIL gracefully

**Output model:**
```python
class DNSProfile(BaseModel):
    nameservers: list[str]
    cloud_provider: str | None      # "AWS", "Cloudflare", "GCP", "Azure", None
    mx_records: list[str]
    email_provider: str | None      # "Google Workspace", "Microsoft 365", "Custom", None
    has_spf: bool
    has_dkim: bool
    has_dmarc: bool
    txt_records: list[str]          # Raw TXT for further analysis
```

#### 2.2 SSL Analyzer — `services/ssl_analyzer.py` (new)

```python
class SSLAnalyzer:
    """Async SSL certificate analysis."""

    async def analyze(self, domain: str) -> SSLProfile:
        """Returns cert issuer, expiry, SANs, health indicators."""
        ...
```

**Implementation details:**
- `ssl` + `asyncio.open_connection()` for async TLS handshake
- Extract issuer, subject, SANs, notBefore/notAfter, signature algorithm
- Infer automation: Let's Encrypt + 90-day validity = automated; long validity = manual
- Semaphore of 5, 0.1s delay
- Handle connection refused, timeout, SSL errors

**Output model:**
```python
class SSLProfile(BaseModel):
    issuer: str | None
    subject_cn: str | None
    sans: list[str]
    not_before: datetime | None
    not_after: datetime | None
    days_until_expiry: int | None
    is_wildcard: bool
    is_automated: bool              # Let's Encrypt / short validity
    signature_algorithm: str | None
```

#### 2.3 Pipeline integration
**File:** `api/jobs.py`

Add DNS and SSL analysis in parallel with the existing `wappalyzer_service.analyze_multiple_domains()` call:

```python
# In _run_research_pipeline(), after Firecrawl scrape:
tech_by_domain, dns_profile, ssl_profile = await asyncio.gather(
    wappalyzer_service.analyze_multiple_domains(main_url=company_url, main_html=scraped_content.homepage_html),
    dns_analyzer.analyze(domain),
    ssl_analyzer.analyze(domain),
)
```

Pass `dns_profile` and `ssl_profile` to Claude prompt builder as new sections.

#### 2.4 Prompt integration
**File:** `services/claude.py`

Add new sections to `_build_user_prompt()`:

```
## DNS & Infrastructure Signals
Cloud Provider: {dns_profile.cloud_provider or "Unknown"}
Email Provider: {dns_profile.email_provider or "Unknown"}
SPF: {dns_profile.has_spf} | DKIM: {dns_profile.has_dkim} | DMARC: {dns_profile.has_dmarc}

## SSL/TLS Certificate
Issuer: {ssl_profile.issuer}
Expires: {ssl_profile.not_after} ({ssl_profile.days_until_expiry} days)
Automated Renewal: {ssl_profile.is_automated}
SANs: {len(ssl_profile.sans)} domains
```

#### Deliverables:
- [ ] DNS analyzer returning cloud/email provider, SPF/DKIM/DMARC
- [ ] SSL analyzer returning cert health and automation detection
- [ ] Both wired into pipeline and prompt
- [ ] Tests with mocked DNS/SSL responses

#### Verification:
```bash
pytest tests/test_dns_analyzer.py tests/test_ssl_analyzer.py -v
pytest tests/ -x -q
```

---

### Phase 3: Security Header Scoring + Robots Signals + Structured Job Parsing

**Goal:** Extract more signal from data we already fetch.

#### 3.1 Security header scoring
**File:** `services/wappalyzer.py`

Add `_score_security_headers(headers: dict) -> SecurityPosture`:

```python
class SecurityPosture(BaseModel):
    score: int                      # 0-100
    present: list[str]              # Headers that are set
    missing: list[str]              # Headers that should be set

SECURITY_HEADERS = [
    "strict-transport-security",
    "content-security-policy",
    "x-frame-options",
    "x-content-type-options",
    "referrer-policy",
    "permissions-policy",
]
```

Call this on the main domain's response headers. Pass result to prompt and pain inference.

#### 3.2 Robots.txt signal extraction
**File:** `services/wappalyzer.py`

Add `_extract_robots_signals(rp: RobotFileParser) -> RobotsSignals`:

```python
class RobotsSignals(BaseModel):
    has_api: bool                   # /api or /graphql disallowed
    has_admin: bool                 # /admin or /wp-admin disallowed
    crawl_delay: int | None         # Crawl-delay value
    disallowed_count: int           # Total disallowed paths
```

#### 3.3 Structured job posting parser — `services/job_parser.py` (new)

```python
class JobParser:
    """Extract structured tech signals from job posting markdown."""

    # Curated keyword list (~150 technologies), not the full 1,270
    TECH_KEYWORDS: dict[str, str]   # keyword -> canonical name

    def parse(self, job_text: str) -> JobSignals:
        """Extract tech mentions, role types, and time signals."""
        ...

class JobSignals(BaseModel):
    technologies_mentioned: list[TechMention]  # (name, count, context_snippet)
    role_types: list[str]           # "DevOps", "Data Engineer", "SRE", etc.
    seniority_signals: list[str]    # "Staff", "Principal", "VP", etc.
    time_open_signals: list[str]    # "posted 90 days ago", etc.
```

**Integration:** Called on `scraped_content.job_postings` before Claude generation. Output injected as structured `## Parsed Job Signals` section alongside raw job text.

#### Deliverables:
- [ ] Security posture scoring from headers
- [ ] Robots.txt signal extraction
- [ ] Job posting parser with ~150 tech keywords
- [ ] All integrated into prompt
- [ ] Tests for each

---

### Phase 4: Pain Inference Engine

**Goal:** Programmatically detect pain patterns from combined signals and inject them into Claude's prompt as structured evidence, improving scoring consistency.

#### 4.1 Pain rule engine — `services/pain_inference.py` (new)

```python
@dataclass
class PainRule:
    id: str
    name: str
    pain_category: str
    required: Callable[[SignalBundle], bool]   # Must return True for rule to fire
    intensity: Callable[[SignalBundle], float]  # Returns 0.0-1.0
    pvp_template: str

class PainInferenceEngine:
    rules: list[PainRule]

    def evaluate(self, signals: SignalBundle) -> list[PainInference]:
        """Run all rules against collected signals, return matches."""
        ...
```

`SignalBundle` is a simple container holding all collected data for a domain:
```python
@dataclass
class SignalBundle:
    tech_by_domain: dict[str, TechStack]
    dns_profile: DNSProfile | None
    ssl_profile: SSLProfile | None
    security_posture: SecurityPosture | None
    robots_signals: RobotsSignals | None
    job_signals: JobSignals | None
    firmographics: str | None
```

#### 4.2 Initial pain rules (10 rules)

| Rule | Required Signals | Intensity Calc | PVP Template |
|------|-----------------|----------------|--------------|
| **Identity Fragmentation** | 3+ analytics tools detected | +0.15 per tool over 2 | "Your {count} analytics tools are telling {count} different stories about the same customer..." |
| **Technical Debt** | Legacy backend (PHP < 8, old jQuery) + modern frontend | +0.3 if version detectable and old | "Your frontend has evolved but your backend hasn't kept pace..." |
| **Security Posture Gap** | security_posture_score < 40 | +0.1 per missing header | "Your security posture has {count} gaps that enterprise buyers will flag in vendor assessments..." |
| **Scaling Pressure** | Recent funding (from firmographics) + infrastructure hiring (from job signals) | +0.5 base | "Post-funding, the infrastructure that got you here won't get you there..." |
| **Multi-Cloud Complexity** | 2+ cloud providers in DNS + headers | +0.2 per provider over 1 | "Managing infrastructure across {providers} creates hidden coordination costs..." |
| **Email Deliverability Risk** | Missing SPF or DKIM or DMARC | +0.2 per missing protocol | "Your email authentication has gaps that inbox providers are increasingly penalizing..." |
| **Certificate Management Gap** | Cert expiring < 30 days + not automated | +0.6 | "Your SSL certificate expires in {days} days and shows no automation..." |
| **Marketing/Product Tech Mismatch** | Different frameworks on marketing vs app subdomain | +0.3 base | "Your product runs on {product_tech} while marketing is on {marketing_tech} — a sign of disconnected engineering priorities..." |
| **Data Infrastructure Pain** | 2+ open data engineer roles (from job signals) | +0.2 per role | "Those data engineering roles have been open because the problem is genuinely hard..." |
| **Tag Bloat** | 8+ script tags from analytics/marketing category | +0.1 per tag over 6 | "Those {count} tracking tags add latency to every page load and fragment your customer view..." |

#### 4.3 Integration with Claude prompt
**File:** `services/claude.py`

Add a new `## Programmatic Pain Signals` section to `_build_user_prompt()`:

```
## Programmatic Pain Signals (from automated analysis)
The following pain patterns were detected by combining multiple signals:

- **Identity Fragmentation** (intensity: 0.75): 5 analytics tools detected (GA4, Mixpanel, Amplitude, Heap, Segment) with no CDP. Your analytics tools can't agree on who your customers are.
- **Security Posture Gap** (intensity: 0.50): Missing 3/6 security headers (CSP, Referrer-Policy, Permissions-Policy).

Use these as STARTING POINTS for your analysis. Validate against other data before including in the research document. Do not repeat them verbatim — synthesize with other evidence.
```

This gives Claude structured pain evidence to work with, rather than hoping it notices sparse signals in a list of technology names.

**Important:** Pain inferences augment Claude's scoring, they don't replace it. Claude still applies the full Pain/Fit/Timing framework (`claude.py:365-443`). The programmatic signals provide higher-quality input.

#### 4.4 Storage
After Claude generates the document, persist `TechSignal` and `PainInference` records to the new database tables linked to `document_id`.

#### Deliverables:
- [ ] Pain inference engine with 10 initial rules
- [ ] SignalBundle aggregation from all analyzers
- [ ] Prompt integration with pain signals section
- [ ] Database persistence of signals and inferences
- [ ] Tests for each rule

#### Verification:
```bash
pytest tests/test_pain_inference.py -v
pytest tests/ -x -q
```

---

### Phase 5: Normalized Storage + Query API

**Goal:** Make detected signals queryable for batch analytics, historical tracking, and future automation rules.

#### 5.1 Migration
Run the new migration adding `tech_signals` and `pain_inferences` tables (see Part 4).

#### 5.2 Write path
**File:** `api/jobs.py`

After `save_document()`, persist collected signals:
```python
doc_id = await save_document(document, user_id=user_id)
await save_tech_signals(doc_id, collected_signals)
await save_pain_inferences(doc_id, pain_inferences)
```

#### 5.3 Read API
**File:** `api/routes.py` (or new `api/signals.py`)

```
GET /api/v1/signals/{domain}
  → Returns cached signals for a domain
  → Query params: since (datetime), signal_type (filter)

GET /api/v1/signals/stats
  → Aggregate: most common technologies, pain categories, detection methods
  → Useful for understanding portfolio-level patterns
```

#### Deliverables:
- [ ] Migration deployed
- [ ] Write path saving signals and inferences per research run
- [ ] Read API for signal retrieval
- [ ] Tests

---

## Part 6: Signal-to-Pain Mapping Reference

### Infrastructure Signals → Pain Inference

| Signal Combination | Pain Category | Intensity | PVP Angle |
|-------------------|---------------|-----------|-----------|
| Multiple cloud providers (DNS NS + header CDN) | Multi-cloud complexity | +0.2/provider over 1 | "Managing across {providers} creates hidden costs..." |
| Legacy backend + modern frontend (detected versions) | Technical debt | +0.3 if version old | "Your frontend evolved but your backend hasn't..." |
| No CDN detected + enterprise indicators | Performance scaling | +0.5 | "Your visitors are waiting longer than they should..." |
| Missing 3+ security headers | Compliance risk | +0.1/header | "Enterprise buyers will flag these gaps..." |
| Cert expiring soon + no automation | Ops maturity gap | +0.6 | "Your cert expires in {days} days..." |
| No SPF + No DKIM + No DMARC | Email deliverability | +0.2/protocol | "Your email authentication has gaps..." |

### Marketing Tech Signals → Pain Inference

| Signal Combination | Pain Category | Intensity | PVP Angle |
|-------------------|---------------|-----------|-----------|
| 3+ analytics tools, no CDP | Identity fragmentation | +0.15/tool over 2 | "Your {count} analytics tools can't agree on who your customers are..." |
| 8+ marketing/analytics script tags | Tag bloat / performance | +0.1/tag over 6 | "Those {count} tags add latency and fragment your data..." |
| CRM + MAP + separate analytics | Data silo pain | +0.4 | "Your customer data lives in {count} places that don't sync..." |
| Different tech on product vs marketing subdomains | Resource misalignment | +0.3 | "Your product and marketing teams are building on different foundations..." |

### Growth Signals → Pain Inference

| Signal Combination | Pain Category | Intensity | PVP Angle |
|-------------------|---------------|-----------|-----------|
| Recent funding + DevOps/SRE hiring | Scaling pressure | +0.5 | "Post-Series {round}, the infra that got you here won't get you there..." |
| 2+ data engineer roles open | Data infrastructure pain | +0.2/role | "Those roles have been open because the problem is hard..." |
| High subdomain count + recent growth signals | Product expansion chaos | +0.3 | "Launching {count} products means {count} more systems to sync..." |

---

## Part 7: Testing & Validation

### Per-phase test requirements

Each phase includes unit tests for new/modified modules. Additionally:

#### Detection accuracy benchmark (Phase 1 deliverable)
```python
# tests/test_detection_benchmark.py
# Run against saved HTML fixtures from 10 known sites
BENCHMARK_CASES = [
    {"fixture": "fixtures/stripe.html", "headers": {...}, "expected_min": ["React", "Next.js", "Stripe.js"]},
    {"fixture": "fixtures/shopify_store.html", "headers": {...}, "expected_min": ["Shopify", "jQuery"]},
    # ... 10 cases
]

def test_detection_coverage():
    for case in BENCHMARK_CASES:
        # Run detector against fixture
        # Assert at least 70% of expected techs detected
```

Fixtures are saved HTML files, not live requests. This makes tests deterministic and avoids network calls.

#### Ethical compliance (continuous)
```python
def test_403_rejected():
    """Verify 403 responses do not trigger follow-up requests."""
    # Already tested in test_wappalyzer.py::TestCheckUrlExists::test_head_403_returns_none

def test_robots_respected():
    """Verify disallowed paths are not probed."""
    # Already tested in test_wappalyzer.py::TestRobotsFiltering::test_disallowed_paths_skipped
```

#### Pain inference integration test
```python
def test_pain_rules_fire_on_realistic_input():
    """Given a SignalBundle from a real-ish detection run, verify expected pain rules trigger."""
    bundle = SignalBundle(
        tech_by_domain={"example.com": TechStack(technologies=[
            DetectedTechnology(name="Google Analytics", category="Analytics", ...),
            DetectedTechnology(name="Mixpanel", category="Analytics", ...),
            DetectedTechnology(name="Amplitude", category="Analytics", ...),
            DetectedTechnology(name="Heap", category="Analytics", ...),
        ])},
        ...
    )
    inferences = engine.evaluate(bundle)
    assert any(i.pain_category == "identity_fragmentation" for i in inferences)
    assert inferences[0].intensity >= 0.3
```

---

## Part 8: Pipeline Integration Summary

### Current pipeline (`api/jobs.py:25-67`):

```
Firecrawl scrape → Wappalyzer scan → Enrichment collection → Claude generation → Save
```

### Revised pipeline:

```
Firecrawl scrape
  ├── Wappalyzer scan (existing, upgraded with inline scripts + cookies)
  ├── DNS analysis (new, parallel)
  └── SSL analysis (new, parallel)
       ↓
Job posting parser (new, on scraped_content.job_postings)
       ↓
Security header scoring (new, on main domain headers)
Robots.txt signal extraction (new, on cached robots.txt)
       ↓
Pain inference engine (new, combines all signals)
       ↓
Enrichment collection (existing, parallel with above where possible)
       ↓
Claude generation (existing, with enriched prompt sections)
       ↓
Save document + Save tech_signals + Save pain_inferences
```

### Key constraint: No new external dependencies beyond `aiodns`

| Dependency | Purpose | Already in project? |
|-----------|---------|-------------------|
| `httpx` | Async HTTP | Yes |
| `beautifulsoup4` + `lxml` | HTML parsing | Yes |
| `aiodns` | Async DNS resolution | **New** |
| `ssl` (stdlib) | TLS cert inspection | Yes (stdlib) |
| `asyncio` (stdlib) | Concurrency | Yes (stdlib) |
| `urllib.robotparser` (stdlib) | robots.txt | Yes (stdlib) |

No Redis. No new web frameworks. No Prometheus (add when there's an ops team to monitor it).

---

## Part 9: What We're NOT Building (scope boundaries)

These items from the v1 PRD are **deferred** until the core system proves value:

| v1 Item | Why Deferred |
|---------|-------------|
| Redis-backed rate limiting | In-process semaphores work at current scale |
| Separate API endpoints (`POST /api/v1/detect`) | Detection is embedded in research pipeline; no external consumers yet |
| Batch processing API (`POST /api/v1/detect/batch`) | List processing already handles batching via `api/jobs.py` |
| Prometheus metrics | No ops infrastructure to consume them yet |
| PVP template library with variable slots | PVP generation already works via Claude + `services/writing.py`; templates are premature |
| `PVPQualityScore` automated scoring | Quality is subjective; user feedback (`research_feedback` table) is the signal |
| Separate fingerprint Python files (`analytics.py`, `marketing.py`) | Existing `technologies.json` has 1,270 entries; don't fragment |
| `structlog` migration | Current `logging` module works fine |
| OpenAPI documentation for detection endpoints | No separate detection endpoints |

---

## Appendix A: Files Changed Per Phase

### Phase 1 (Unlock Existing Fingerprints)
| File | Change |
|------|--------|
| `services/techdetect/webpage.py` | Add inline script extraction, cookie parsing |
| `services/techdetect/fingerprints.py` | Load `js` → inline patterns, load `cookies` patterns |
| `services/techdetect/detector.py` | Add inline script + cookie matching |
| `tests/test_techdetect.py` | Tests for new detection paths |

### Phase 2 (DNS & SSL)
| File | Change |
|------|--------|
| `services/dns_analyzer.py` | **New file** |
| `services/ssl_analyzer.py` | **New file** |
| `api/jobs.py` | Wire analyzers into pipeline |
| `services/claude.py` | Add DNS/SSL prompt sections |
| `tests/test_dns_analyzer.py` | **New file** |
| `tests/test_ssl_analyzer.py` | **New file** |

### Phase 3 (Signal Extraction)
| File | Change |
|------|--------|
| `services/wappalyzer.py` | Add `_score_security_headers()`, `_extract_robots_signals()` |
| `services/job_parser.py` | **New file** |
| `services/claude.py` | Add security/robots/job signal prompt sections |
| `tests/test_job_parser.py` | **New file** |
| `tests/test_wappalyzer.py` | Tests for security scoring + robots signals |

### Phase 4 (Pain Inference)
| File | Change |
|------|--------|
| `services/pain_inference.py` | **New file** |
| `models.py` | Add `TechSignal`, `PainInference`, `SignalBundle` models |
| `services/claude.py` | Add pain signals prompt section |
| `api/jobs.py` | Wire pain inference into pipeline |
| `tests/test_pain_inference.py` | **New file** |

### Phase 5 (Storage + Query)
| File | Change |
|------|--------|
| `migrations/00X_tech_signals.sql` | **New file** — tables for signals + inferences |
| `database.py` | Add `save_tech_signals()`, `save_pain_inferences()`, query functions |
| `api/jobs.py` | Persist signals after document save |
| `api/routes.py` or `api/signals.py` | Signal query endpoints |

---

## Appendix B: Competitive Comparison (updated)

| Capability | Wappalyzer | BuiltWith | Our System (current) | Our System (after this PRD) |
|-----------|-----------|-----------|---------------------|---------------------------|
| HTML/header fingerprinting | 1,500+ techs | 50,000+ | 1,270 techs (5 signal types) | 1,270 techs (8 signal types: +inline scripts, +cookies, +DNS) |
| JS global detection | Yes (browser ext) | Yes | No | Partial (inline script proxy) |
| DNS infrastructure signals | No | Yes | No | Yes |
| SSL cert analysis | No | Limited | No | Yes |
| Pain inference | No | No | No (Claude guesses) | Yes (10+ programmatic rules + Claude) |
| Signal combinations | No | No | Instructed via prompt (inconsistent) | Programmatic + prompt (consistent) |
| Job posting tech extraction | No | No | Claude-parsed (inconsistent) | Programmatic + Claude |
| PVP generation | No | No | Yes (via writing.py) | Yes (with structured pain input) |
| Ethical by design | Unknown | Unknown | Yes | Yes |

---

## Appendix C: Integration with PVP Generation

**Do not modify `services/writing.py` or `data/pvp_examples.md` as part of this work.**

The detection system improves PVP quality by improving the `ResearchDocument` that `writing.py` consumes. The chain is:

```
Detection signals → Pain inferences → Claude prompt → ResearchDocument → writing.py → PVP emails
```

Better detection → better `confirmed_tech_stack`, `business_problems`, `existential_data_points` fields → better PVPs. No changes to the PVP generation layer itself.

---

## Appendix D: Legal Review Checklist (unchanged from v1)

- [ ] robots.txt compliance is sufficient for our use case
- [ ] User-Agent disclosure is appropriate
- [ ] Data retention policy for detected signals
- [ ] PII handling if detected incidentally
- [ ] Terms of service for third-party data sources
- [ ] GDPR/CCPA implications of storing tech data
- [ ] DNS and SSL analysis legality confirmation (standard public queries)
