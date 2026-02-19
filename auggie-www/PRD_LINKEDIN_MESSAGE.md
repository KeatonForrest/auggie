# PRD: LinkedIn Single-Message from Screenshot

## Problem

Sellers research a prospect in Auggie, get a 3-email PEA sequence, and then want to open a conversation on LinkedIn. Today they either:
1. Manually rewrite Email 1 as a shorter LinkedIn message (friction, inconsistent quality)
2. Paste Email 1 directly (too long, wrong tone for LinkedIn)

LinkedIn messages have different constraints than email: shorter, more conversational, no subject line, one shot instead of a sequence.

## Solution

Add a "LinkedIn Message" output option alongside the existing email sequence. When a user uploads a LinkedIn screenshot (profile or post), the system generates a single short message that references the screenshot content and connects it to the research-backed PVP angle.

## Scope

### v1 (this PRD)
- Single LinkedIn message generation from screenshot + research document
- Dedicated LinkedIn system prompt (not reusing the 600-line email prompt)
- Two channel modes: `dm` (default) and `connection_request`, with separate word limits
- Standard PVP angle only (research-driven)
- OCR fallback when screenshot extraction is noisy
- Hard relevance guardrails: prompt constraint + deterministic post-filter
- Output quality gate: structural validation before returning to user

### Post-v1 (explicitly deferred)
- Angle selector (let user pick which research signal to lead with)
- InMail variant (longer, different CTA patterns)
- Comment-on-post generation
- Multi-message LinkedIn sequence

## Channel Modes

LinkedIn has two distinct message surfaces with different constraints:

| Mode | Max chars | Our word limit | Use case |
|------|-----------|----------------|----------|
| `dm` (default) | 8,000 | 50-90 words | Regular DM to an existing connection or open profile |
| `connection_request` | 300 | 25-45 words | Note attached to a connection request |

The frontend passes `mode` as a form field. The system prompt, word limits, and validation thresholds all key off this value. Connection requests need a tighter structure: one sentence of context + one question. No bridge sentence — there's no room.

```python
LINKEDIN_WORD_LIMITS = {
    "dm": 90,
    "connection_request": 45,
}
```

## Architecture

### Data Flow

```
Screenshot (image) ──► VisionService.extract_linkedin_context()
                              │
                              ▼
                       LinkedInContext dict
                              │
Research Document ────────────┤
Product Context ──────────────┤
Channel Mode ─────────────────┤
                              ▼
                   WritingService.generate_linkedin_message()
                              │
                              ├── _build_linkedin_system_prompt(mode)  [NEW, ~100 lines]
                              ├── _build_linkedin_user_prompt()        [NEW]
                              ├── LLM call (writing_model)
                              ├── _parse_linkedin_message()            [NEW]
                              ├── _validate_linkedin_message()         [NEW, quality gate]
                              └── Word-limit enforcement (trim + CTA rescue)
                              │
                              ▼
                       { message, word_count, content_type, mode }
```

### Why a Separate System Prompt

The existing `_build_system_prompt()` loads 600+ lines of PEA framework rules, 3-email structure, subject line rules, and email-specific examples. LinkedIn messages need:
- Different structure (no PEA, no subject lines, no 3-email cadence)
- Different tone (casual peer, not polished email)
- Different constraints (shorter, single CTA, no "sequence arc" logic)
- Different examples

Appending LinkedIn rules to the email prompt would confuse the model and bloat context. A focused ~80-line LinkedIn prompt will produce better output with lower token cost.

## Implementation

### 1. Feature Flag

**`config.py`** — add after `pain_frontend_rule_enabled`:
```python
linkedin_message_enabled: bool = False
```

**`.env.example`**:
```
LINKEDIN_MESSAGE_ENABLED=false
```

### 2. VisionService Extension (`services/vision.py`)

Add a new extraction prompt and method alongside the existing persona extraction.

**`LINKEDIN_CONTEXT_PROMPT`** — new module-level constant:
```
Extract the following from this LinkedIn screenshot.

Determine the CONTENT TYPE first:
- PROFILE: A LinkedIn profile page (shows name, headline, experience, about)
- POST: A LinkedIn post or article (shows author, post content, reactions)
- OTHER: Not a LinkedIn screenshot

Output in this exact format (leave blank if not visible):

CONTENT_TYPE: [PROFILE|POST|OTHER]
AUTHOR_NAME: [person's name]
AUTHOR_TITLE: [job title if visible]
AUTHOR_COMPANY: [company if visible]
FOCUS_SNIPPET: [most notable content — for PROFILE: headline + about summary (first 200 chars); for POST: the post text (first 300 chars)]
ENGAGEMENT: [for POST: approximate reaction/comment count if visible; for PROFILE: leave blank]

If the image is not from LinkedIn, respond with:
NOT_LINKEDIN: [brief description of what the image shows]
```

**`extract_linkedin_context()`** — new method on VisionService:
- Accepts `image_bytes: bytes, content_type: str`
- Calls vision model with `LINKEDIN_CONTEXT_PROMPT`
- Returns `dict` with keys: `content_type`, `author_name`, `author_title`, `author_company`, `focus_snippet`, `engagement`
- Returns `{"content_type": "other"}` if not LinkedIn or extraction fails

**`_parse_linkedin_context()`** — new private method:
- Parses structured output into dict (same regex approach as `_parse_persona`)
- Validates `content_type` is one of PROFILE/POST/OTHER

**OCR Fallback**: If `focus_snippet` is empty or < 10 chars but `content_type` is PROFILE or POST, set a `low_confidence: True` flag on the context dict. The writing prompt will use this to fall back to research-only angles rather than referencing screenshot content the model couldn't read.

### 3. LinkedIn System Prompt (`services/writing.py`)

**`_build_linkedin_system_prompt(mode: str)`** — new method on WritingService. Accepts `"dm"` or `"connection_request"`. ~100 lines covering:

**Shared rules (both modes):**
```
You write single LinkedIn messages for B2B sellers.

ROLE: You are the seller, writing a direct message to a prospect.
The message opens a conversation. It does not close a deal.

CONSTRAINTS:
- No subject line. LinkedIn messages don't have them.
- No "I noticed on your LinkedIn..." or "I saw your post about..."
  — reference the content naturally as if you already knew it.
- No product pitches. Earn curiosity, don't sell.
- Write like a peer texting a colleague, not an email marketer.
- No emdashes. No bold. No bullet points. Plain conversational text.
- CTA must be low-friction: a question, not a meeting request.
  Good: "curious how you're thinking about X"
  Bad: "would love 15 minutes to discuss"
- The message MUST end with exactly one question. One `?`, at the end. Not two questions, not zero.

RELEVANCE GUARDRAIL:
- Only reference pains and signals that map directly to what the seller
  sells (their product category and stated problems solved).
- Infrastructure, frontend, CDN, and dev-tooling signals are OFF LIMITS
  unless the seller category is explicitly web performance, frontend,
  or devtools.
- When in doubt, use business pain (growth, ops, cost, compliance)
  over technical observations.

OUTPUT FORMAT:
Message:
[the message text]
```

**DM mode additions:**
```
WORD LIMIT: 50-90 words. Aim for this range. The ceiling is enforced; the floor is a target.

STRUCTURE:
1. Hook (1-2 sentences): Reference something specific — a post they wrote,
   a career move, a company initiative. Connect it to a business pattern.
2. Bridge (1 sentence): Why this matters now / what you've seen at
   similar companies.
3. CTA (1 sentence): A genuine question that invites a reply.
```

**Connection request mode additions:**
```
WORD LIMIT: 25-45 words. Aim for this range. The ceiling is enforced;
the floor is a target. Connection request notes are capped at 300
characters by LinkedIn — every word counts.

STRUCTURE:
1. Context (1 sentence): One specific, concrete reason you're reaching out.
2. CTA (1 sentence): A genuine question that invites them to accept.

No bridge sentence. There is no room. Get to the point.
```

### 4. LinkedIn User Prompt (`services/writing.py`)

**`_build_linkedin_user_prompt()`** — new method:
- Accepts: `report: str, linkedin_context: dict, product_context: str, persona_context: str, problems_solved: str, mode: str`
- Assembles:
  1. Task instruction: "Write a LinkedIn {mode} message to this prospect."
  2. Screenshot context block (if `low_confidence` is False):
     ```
     <screenshot_context>
     Content type: {profile|post}
     Author: {name}, {title} at {company}
     Key content: {focus_snippet}
     </screenshot_context>
     ```
  3. If `low_confidence` is True: "Screenshot was unclear. Use research signals only — do not reference specific LinkedIn content."
  4. Abbreviated research report (company overview, business problems, talking points — skip the full tech stack, DNS, security sections that are email-specific)
  5. Explicit relevance anchor (always included):
     ```
     **SELLER CONTEXT — USE THIS TO FILTER SIGNALS:**
     Product category: {product_context}
     Problems solved: {problems_solved}
     Only reference pains that a buyer would connect to these capabilities.
     ```
  6. Product-relevance constraint from `_CATEGORY_DENYLISTS` if category detected (reuse existing logic)

### 5. Generation Method (`services/writing.py`)

**`generate_linkedin_message()`** — new async method on WritingService:

```python
async def generate_linkedin_message(
    self,
    document: ResearchDocument,
    product_context: str,
    linkedin_context: dict,
    mode: str = "dm",
    retrieved_materials: str = "",
    seller_company: str = "",
    problems_solved: str = "",
    persona_context: str = "",
    custom_signals: str = "",
) -> dict:
```

Returns: `{"message": str, "word_count": int, "content_type": str, "mode": str}`

Flow:
1. Validate `mode` is `"dm"` or `"connection_request"` (default `"dm"`)
2. Build abbreviated report from `_build_report()` (reuse existing method)
3. Apply relevance gate if enabled (reuse existing `_detect_product_category` + `_apply_relevance_gate`)
4. Build LinkedIn system prompt (with mode) + user prompt
5. Single LLM call (`writing_model`)
6. Parse response: extract text after `Message:` prefix
7. Post-processing: strip emdashes, bold markers (reuse existing cleanup)
8. **Relevance post-filter** (`_filter_linkedin_relevance`): scan message for blocked signal families from `_CATEGORY_DENYLISTS`. If blocked patterns found without linkage overrides, reject and re-prompt once with: "Your message references [blocked_term]. This is not relevant to what the seller sells. Rewrite using only signals from the research report that connect to: [problems_solved]." (Single retry, not a loop.)
9. **Word-limit normalization** (runs before quality gate):
    - Limit = `LINKEDIN_WORD_LIMITS[mode]` (90 for dm, 45 for connection_request)
    - If over limit: deterministic sentence-preserving trim via `_trim_to_word_limit(body, limit)`
    - **CTA rescue**: if trim removed the trailing question (no `?` as the last non-whitespace char), do one cheap LLM rewrite: "Rewrite this LinkedIn message to be under {limit} words. It MUST end with a question. Keep the same message and tone. Output ONLY the message text.\n\n{body}"
    - If rewrite still over limit or missing `?`: keep trimmed version, set `cta_rescued = False`
10. **Char-limit normalization** (connection_request only, before quality gate):
    - If `len(message) > 300`: truncate at last sentence boundary within 300 chars
    - If truncation removes `?`: apply same CTA rescue rewrite with additional "under 300 characters" constraint
11. **Quality gate** (`_validate_linkedin_message`): check structural acceptance criteria (see Quality Gate section). Runs AFTER normalization so word/char limits are already enforced. If fails, return error with specific failure reason — do not silently pass.
12. Return result dict with `cta_rescued` flag

### 6. Route Handler (`routes/research.py`)

**`POST /document/{doc_id}/linkedin-message`** — new route:

```python
@router.post("/document/{doc_id}/linkedin-message")
async def generate_linkedin_message(
    doc_id: int,
    screenshot: UploadFile = File(None),  # optional — allows research-only fallback
    mode: str = Form("dm"),              # "dm" or "connection_request"
    user: dict = Depends(require_onboarding),
):
```

Flow:
1. Check `linkedin_message_enabled` flag — return 404 if off
2. Validate `mode` in `{"dm", "connection_request"}` — return 422 if invalid
3. Load document, validate exists and belongs to user
4. If screenshot provided:
   a. Extract LinkedIn context via `vision_service.extract_linkedin_context()`
   b. If `content_type == "other"`: return 422 with `{"error": {"code": "not_linkedin", "message": "Screenshot does not appear to be from LinkedIn. Upload a LinkedIn profile or post screenshot, or use 'Generate from research only'."}}`
5. If no screenshot: set `linkedin_context = {"content_type": "none", "low_confidence": True}` (research-only mode)
6. Retrieve materials (non-fatal, same pattern as outreach route)
7. Call `writing_service.generate_linkedin_message(mode=mode, ...)`
8. Return `{"success": True, "message": ..., "word_count": ..., "content_type": ..., "mode": ...}`

### 7. Frontend (`templates/document.html`)

Add a "LinkedIn Message" tab/button in the outreach modal alongside the existing email generation. When clicked:

**Channel selector** (toggle pills above the screenshot upload):
- "Direct Message" (default, selected)
- "Connection Request"
- Selection stored as `mode` form field, sent with the POST

**Screenshot upload**:
- Reuse existing dropzone component
- Screenshot is **recommended but optional** — show helper text: "Upload a LinkedIn profile or post screenshot for a more personalized message"
- **"Generate from research only"** button below the dropzone — skips screenshot, sends POST without file
- If screenshot upload returns `not_linkedin` error: show inline toast "This doesn't look like a LinkedIn screenshot" + keep the "Generate from research only" button visible as fallback

**Result display**:
- Single text block (no email cards, no subject lines)
- Show word count and char count (important for connection requests: "42 words, 238/300 chars")
- If `connection_request` mode and chars > 280: show amber warning "Close to LinkedIn's 300 character limit"
- "Copy" button for easy paste into LinkedIn
- If `cta_rescued == False`: show subtle note "Tip: consider adding a question at the end to invite a reply"

### 8. Quality Gate (`services/writing.py`)

**`_validate_linkedin_message(message: str, mode: str, company_name: str) -> tuple[bool, str]`**

Deterministic checks run AFTER word-limit and char-limit normalization (steps 9-10). Returns `(is_valid, error_reason)`.

| Check | Rule | Failure action |
|-------|------|----------------|
| **Trailing question** | Message ends with exactly 1 `?` (canonical rule: `re.search(r'\?\s*$', message)` AND `message.count('?') == 1`) | Fail: "Message must end with exactly one question" |
| **Word count in range** | `dm`: 10 ≤ words ≤ 90. `connection_request`: 10 ≤ words ≤ 45. (Min catches empty/degenerate output; max should already be enforced by trim but acts as safety net) | Fail: "Message is {n} words, limit is {limit}" |
| **Char limit** | `connection_request` mode: `len(message) <= 300` (safety net — normalization should handle this, but gate catches edge cases) | Fail: "Connection request exceeds 300 character limit" |
| **No banned phrases** | Scan for: "I noticed on your LinkedIn", "I saw your post", "I'd love 15 minutes", "I'd love to grab 15", "would love 15 minutes" | Fail: "Message contains banned phrase: {phrase}" |
| **Has company anchor** | Message contains `company_name` (case-insensitive) | Fail: "Message lacks a prospect-specific anchor" |

**Banned phrase rationale**: Only ban phrases that are unambiguously bad LinkedIn openers. Generic phrases like "according to" and "based on your" are removed from the ban list — they appear in natural, valid messages (e.g., "based on your team's growth" is fine). The prompt's relevance guardrail handles source-citing ("according to SEC filings") without needing a blunt phrase ban.

**Note**: Relevance filtering runs in step 8 (before normalization and gate), not in the gate itself. The gate is purely structural.

On validation failure: return error to the caller. Do not silently pass a bad message. The route handler returns 422 with the failure reason so the frontend can show "Generation didn't meet quality bar — try again" + a retry button.

### 9. Tests

**`tests/test_writing.py`:**

**`TestLinkedInSystemPrompt`** (4 tests):
- DM mode: prompt contains 50-90 word limit, 3-part structure, relevance guardrail
- Connection request mode: prompt contains 25-45 word limit, 2-part structure, 300-char note
- Both modes: prompt does NOT contain PEA framework or email-specific rules
- Both modes: prompt contains relevance guardrail ("Only reference pains that map directly")

**`TestLinkedInUserPrompt`** (5 tests):
- Profile screenshot → context block with name/title/snippet
- Post screenshot → context block with post content
- Low-confidence screenshot → fallback instruction, no screenshot context
- Research-only (no screenshot) → no screenshot context, research signals present
- Seller context block always present with product_context + problems_solved

**`TestLinkedInRelevanceFilter`** (4 tests):
- DB seller + message mentioning React → triggers re-prompt
- DB seller + message mentioning query performance → passes
- Unknown seller category → no filtering
- DB seller + CDN with "database bottleneck" linkage → passes (linkage override)

**`TestLinkedInQualityGate`** (9 tests):
- Valid message ending with `?`, within word limit → passes
- No question mark → fails with "must end with exactly one question"
- `?` in middle but not at end → fails (trailing `?` check via regex)
- Multiple question marks → fails (count == 1 check)
- Banned phrase "I noticed on your LinkedIn" → fails
- Valid phrase "based on your team's growth" → passes (not in ban list)
- Missing company anchor → fails
- DM at 95 words → fails word count ("Message is 95 words, limit is 90")
- Connection request at 310 chars → fails char limit

**`TestLinkedInMessageGeneration`** (5 tests):
- Happy path DM: mocked LLM returns valid message, parsed correctly, word_count within limit
- Happy path connection_request: message under 45 words and 300 chars
- Over word limit with CTA intact: deterministic trim, question preserved
- Over word limit, trim kills CTA: one LLM rewrite attempted, `cta_rescued` flag set
- Empty/malformed response: returns error gracefully

**`TestLinkedInChannelModes`** (3 tests):
- DM mode uses 90-word limit
- Connection request mode uses 45-word limit
- Invalid mode raises ValueError

**`tests/test_vision.py`** (new file or extend existing):

**`TestLinkedInContextExtraction`** (5 tests):
- Profile screenshot text → parsed correctly with content_type=PROFILE
- Post screenshot text → parsed correctly with content_type=POST
- NOT_LINKEDIN response → returns `{"content_type": "other"}`
- Missing fields → partial dict with available fields
- Low-confidence: PROFILE with empty focus_snippet → `low_confidence: True`

## Word Limit Rationale

**DM mode (50-90 words):**
- A hook (2 sentences) + bridge (1 sentence) + CTA (1 sentence) = 4 sentences. At 50 words that's ~12 words/sentence — natural prose.
- 90 words ≈ 500 chars, well within LinkedIn DM's 8,000-char limit and short enough to read without scrolling on mobile.

**Connection request mode (25-45 words):**
- LinkedIn hard-caps connection request notes at 300 characters.
- 45 words ≈ 270 chars, leaving margin for the platform limit.
- Structure is context (1 sentence) + CTA (1 sentence). No bridge — there's no room.
- The char-count check (`len(message) <= 300`) is the true gate; word count is a generation guide.

**Trim strategy:**
- Deterministic sentence-preserving trim (reuses existing `_trim_to_word_limit`) handles overflow without an LLM shorten call.
- If trim removes the trailing question (CTA), one cheap LLM rewrite pass restores it. This keeps latency to 1-2 LLM calls max (generation + optional CTA rescue), vs. the email pipeline's multi-pass shorten loop.

## Files Touched

| File | Change |
|------|--------|
| `config.py` | +1 line: `linkedin_message_enabled` flag |
| `.env.example` | +1 line: env var |
| `services/vision.py` | +1 prompt constant, +2 methods (`extract_linkedin_context`, `_parse_linkedin_context`) |
| `services/writing.py` | +1 constant (`LINKEDIN_WORD_LIMITS`), +5 methods (`_build_linkedin_system_prompt`, `_build_linkedin_user_prompt`, `generate_linkedin_message`, `_validate_linkedin_message`, `_filter_linkedin_relevance`) |
| `routes/research.py` | +1 route handler (`POST /document/{doc_id}/linkedin-message`) |
| `templates/document.html` | LinkedIn tab in outreach modal, channel selector, copy button, fallback UX |
| `tests/test_writing.py` | 6 test classes (~30 tests) |
| `tests/test_vision.py` | 1 test class (~5 tests) — new file or extend existing |

## Non-Goals

- **No new models.** Uses existing `writing_model` and `vision_model`.
- **No new database tables.** LinkedIn messages are returned directly, not stored.
- **No angle selector.** v1 uses the standard PVP angle from research. Users who want a different hook can regenerate or edit manually.
- **No InMail mode.** Single message type for now.
- **No post-comment generation.** Different enough format to warrant its own feature.

## Risks

| Risk | Mitigation |
|------|------------|
| Vision model can't read screenshot (low-res, partial scroll) | `low_confidence` flag → fall back to research-only message; "Generate from research only" button always available |
| Message feels generic without screenshot signal | Research report still provides company-specific hooks; quality gate requires company anchor |
| Deterministic trim damages CTA | CTA rescue: if trim removes trailing `?`, one cheap LLM rewrite pass with strict word cap + "must end with question" constraint |
| Irrelevant signals leak into short message | 3-layer defense: prompt relevance guardrail, `_filter_linkedin_relevance` post-filter with re-prompt, quality gate banned-phrase check |
| Connection request exceeds 300-char limit | Char-count gate in `_validate_linkedin_message`; additional trim + rewrite if needed |
| User uploads non-LinkedIn screenshot | `content_type: "other"` → 422 with actionable error message + "Generate from research only" fallback in UI |
| Quality gate too strict, high rejection rate | Gate checks are structural (has question, no banned phrases, has anchor) not subjective; monitor rejection rate and loosen if > 20% |

## Acceptance Criteria

Feature is shippable when ALL of the following pass:

### Functional
- [ ] DM mode generates a message up to 90 words, ending with exactly one `?`, passing quality gate
- [ ] Connection request mode generates a message up to 45 words, ≤300 chars, ending with exactly one `?`, passing quality gate
- [ ] Screenshot upload extracts profile and post content correctly
- [ ] Non-LinkedIn screenshot returns 422 with actionable error
- [ ] No-screenshot path generates research-only message
- [ ] Low-confidence OCR falls back to research-only (no hallucinated screenshot references)
- [ ] Feature flag off → 404 on the endpoint, no UI visible

### Quality Gates (deterministic, tested)
- [ ] Every returned message ends with exactly 1 `?` (`re.search(r'\?\s*$')` AND `count('?') == 1`)
- [ ] Every returned message has word count within mode limit (dm: 10-90, connection_request: 10-45)
- [ ] No message contains banned phrases: "I noticed on your LinkedIn", "I saw your post", "I'd love 15 minutes", "I'd love to grab 15", "would love 15 minutes"
- [ ] Every message references prospect company name (case-insensitive match)
- [ ] For detected seller categories: no blocked signal families appear without linkage override (enforced by relevance post-filter before gate)
- [ ] Connection request messages are ≤ 300 characters

### Relevance
- [ ] DB seller + prospect with React/CDN signals → message does NOT mention React/CDN
- [ ] DB seller + prospect with query perf signals → message DOES reference query performance
- [ ] Generic seller (no category detected) → no filtering applied
- [ ] Prompt includes seller context block with product_context + problems_solved

### UX
- [ ] Channel selector (DM / Connection Request) visible and functional
- [ ] Copy button works, copies plain text
- [ ] Connection request mode shows char count with warning at >280
- [ ] Failed quality gate shows "try again" with retry button
- [ ] `not_linkedin` error shows toast + "Generate from research only" fallback
- [ ] CTA rescue failure shows tip about adding a question

### Tests
- [ ] All 30 writing tests pass (`tests/test_writing.py`)
- [ ] All 5 vision tests pass (`tests/test_vision.py`)
- [ ] Full suite passes with no regressions (`python3 -m pytest -q`)
