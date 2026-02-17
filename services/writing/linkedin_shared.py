"""linkedin_shared.py - Shared LinkedIn prompt text, validators, and utilities."""

import re

from services.writing.postprocess import extract_company_core, company_anchor_match
from services.writing.types import GenerationContext, _CATEGORY_DENYLISTS


# ---------------------------------------------------------------------------
# Shared system prompt text
# ---------------------------------------------------------------------------

SHARED_LINKEDIN_RULES = """You write single LinkedIn messages for B2B sellers.

ROLE: You are the seller, writing a direct message to a prospect.
The message opens a conversation. It does not close a deal.

CONSTRAINTS:
- No subject line. LinkedIn messages don't have them.
- No robotic LinkedIn openers like "I noticed on your LinkedIn...",
  "I came across your profile...", or "I saw your LinkedIn post about..."
  "I noticed..." and "I saw..." are fine when followed by a specific signal,
  not a reference to the platform itself.
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
[the message text]"""


# ---------------------------------------------------------------------------
# Shared user prompt builder
# ---------------------------------------------------------------------------

def build_linkedin_user_prompt(ctx: GenerationContext) -> str:
    """Build the user prompt for LinkedIn message generation."""
    mode_label = "direct message" if ctx.mode == "dm" else "connection request note"
    parts = [f"Write a LinkedIn {mode_label} to this prospect."]

    # Company anchor instruction
    if ctx.company_name:
        core = extract_company_core(ctx.company_name)
        parts.append(f'The message MUST mention the company by name. Use this token: "{core}".')

    # Screenshot context
    low_confidence = ctx.linkedin_context.get("low_confidence", True)
    ct = ctx.linkedin_context.get("content_type", "none")

    if not low_confidence and ct in ("profile", "post"):
        ctx_lines = [f"Content type: {ct}"]
        name = ctx.linkedin_context.get("author_name", "")
        title = ctx.linkedin_context.get("author_title", "")
        company = ctx.linkedin_context.get("author_company", "")
        author_parts = [p for p in [name, title, company] if p]
        if author_parts:
            ctx_lines.append(f"Author: {', '.join(author_parts)}")
        snippet = ctx.linkedin_context.get("focus_snippet", "")
        if snippet:
            ctx_lines.append(f"Key content: {snippet}")
        engagement = ctx.linkedin_context.get("engagement", "")
        if engagement:
            ctx_lines.append(f"Engagement: {engagement}")
        parts.append("<screenshot_context>\n" + "\n".join(ctx_lines) + "\n</screenshot_context>")
    else:
        parts.append("Screenshot was unclear or not provided. Use research signals only -- do not reference specific LinkedIn content.")

    # Research report
    parts.append(f"<report>\n{ctx.report}\n</report>")

    # Seller context (always included)
    seller_block = (
        "**SELLER CONTEXT -- USE THIS TO FILTER SIGNALS:**\n"
        f"Product category: {ctx.product_context}\n"
        f"Problems solved: {ctx.problems_solved}\n"
        "Only reference pains that a buyer would connect to these capabilities."
    )
    parts.append(seller_block)

    # Product-relevance constraint from denylists
    if ctx.product_category and ctx.product_category in _CATEGORY_DENYLISTS:
        denylist = _CATEGORY_DENYLISTS[ctx.product_category]
        parts.append(
            f"**PRODUCT-RELEVANCE CONSTRAINT ({ctx.product_category.upper()} SELLER):**\n"
            "\n"
            "Use ONLY signals causally connected to the seller's product category. "
            "Reject weak or indirect signal connections even if technically interesting.\n"
            "\n"
            f"{denylist['prompt_constraint']}"
        )

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Shared output parser
# ---------------------------------------------------------------------------

def parse_linkedin_output(raw: str) -> str:
    """Extract message text after 'Message:' prefix."""
    message = raw.strip()
    msg_match = re.search(r"^Message:\s*", message, re.MULTILINE)
    if msg_match:
        message = message[msg_match.end():].strip()
    return message


# ---------------------------------------------------------------------------
# Shared validators
# ---------------------------------------------------------------------------

def validate_linkedin_banned_phrases(msg_lower: str) -> tuple[bool, str]:
    """Check for robotic LinkedIn cliches.

    Returns (is_ok, error_reason). is_ok=True means no banned phrases found.
    """
    banned = [
        "I noticed on your LinkedIn",
        "I noticed on your profile",
        "I noticed your LinkedIn",
        "I saw your post on LinkedIn",
        "I saw your LinkedIn",
        "I came across your profile",
        "I'd love 15 minutes",
        "I'd love to grab 15",
        "would love 15 minutes",
    ]
    for phrase in banned:
        if phrase.lower() in msg_lower:
            return False, f"Message contains banned phrase: {phrase}"
    return True, ""


def validate_linkedin_anchor(msg_lower: str, company_name: str) -> tuple[bool, str]:
    """Check if message contains company name anchor.

    Returns (is_ok, error_reason).
    """
    if not company_anchor_match(company_name, msg_lower):
        return False, "Message lacks a prospect-specific anchor"
    return True, ""


def validate_linkedin_question(message: str) -> tuple[bool, str]:
    """Check that message ends with exactly one question.

    Returns (is_ok, error_reason).
    """
    if not re.search(r'\?\s*$', message):
        return False, "Message must end with exactly one question"
    if message.count('?') != 1:
        return False, "Message must end with exactly one question"
    return True, ""


# ---------------------------------------------------------------------------
# Relevance filter
# ---------------------------------------------------------------------------

def filter_relevance(message: str, category: str) -> tuple[bool, list[str]]:
    """Scan a LinkedIn message for blocked signal families.

    Returns (is_clean, blocked_terms). is_clean=True means no blocked patterns
    found or category not in denylists.
    """
    if not category or category not in _CATEGORY_DENYLISTS:
        return True, []

    denylist = _CATEGORY_DENYLISTS[category]
    msg_lower = message.lower()
    blocked_terms = []

    for pattern in denylist["blocked_patterns"]:
        if pattern in msg_lower:
            has_linkage = any(ov in msg_lower for ov in denylist["linkage_overrides"])
            if not has_linkage:
                blocked_terms.append(pattern)

    return len(blocked_terms) == 0, blocked_terms
