"""postprocess.py - Pure text post-processing utilities for generated content."""

import re


def strip_emdashes(text: str) -> str:
    """Replace unicode dashes with commas for natural phrasing."""
    text = (
        text
        .replace("\u2014", ", ")   # em dash
        .replace("\u2013", ", ")   # en dash
        .replace("\u2015", ", ")   # horizontal bar
        .replace("\u2012", ", ")   # figure dash
    )
    # Clean up spacing artifacts from pre-spaced dashes
    text = text.replace(" , ", ", ")
    text = text.replace(" ,", ",")
    text = text.replace("  ", " ")
    return text


def strip_bold(text: str) -> str:
    """Remove markdown bold/italic markers."""
    return re.sub(r"\*+(.+?)\*+", r"\1", text)


def postprocess(text: str) -> str:
    """Apply all post-processing: emdash replacement + bold stripping."""
    return strip_bold(strip_emdashes(text))


def trim_to_word_limit(body: str, limit: int) -> str:
    """Deterministically trim text to a hard word cap."""
    words = body.split()
    if len(words) <= limit:
        return body.strip()

    # Prefer sentence-preserving trim first.
    sentences = re.split(r"(?<=[.!?])\s+", body.strip())
    kept: list[str] = []
    kept_words = 0
    for sentence in sentences:
        sentence_words = sentence.split()
        if not sentence_words:
            continue
        if kept_words + len(sentence_words) > limit:
            break
        kept.append(sentence.strip())
        kept_words += len(sentence_words)

    if kept and kept_words > 0:
        return " ".join(kept).strip()

    # Fallback: strict token trim.
    return " ".join(words[:limit]).strip()


def extract_company_core(company_name: str) -> str:
    """Extract the core company token from a company name or domain.

    Examples:
        "MongoDB, Inc." -> "mongodb"
        "fortive.com"   -> "fortive"
        "nike.com"      -> "nike"
        "Acme Corp"     -> "acme"
    """
    name_lower = company_name.lower().strip()

    # Strip common legal/corporate suffixes
    suffixes = [
        ", inc.", ", inc", " inc.", " inc",
        ", corp.", ", corp", " corp.", " corp",
        ", llc", " llc",
        ", ltd.", ", ltd", " ltd.", " ltd",
        ", co.", " co.",
        ".com", ".io", ".ai", ".co", ".org", ".net",
    ]
    core = name_lower
    for suffix in suffixes:
        if core.endswith(suffix):
            core = core[: -len(suffix)].strip()
            break

    core = core.rstrip(",. ")
    return core if len(core) >= 3 else name_lower


def deterministic_anchor_insert(message: str, company_name: str) -> str:
    """Insert the company name into the first sentence of the message.

    Used as a last-resort fallback when LLM-based anchor rescue fails.
    Prepends 'At {Core}, ' to the message opening so the anchor check passes.
    """
    core = extract_company_core(company_name)
    if not core:
        return message

    # Capitalize the core name for natural reading
    core_display = core.capitalize()

    # If message starts with a capital letter, lowercase it for splicing
    if message and message[0].isupper():
        message = message[0].lower() + message[1:]

    return f"At {core_display}, {message}"


def company_anchor_match(company_name: str, msg_lower: str) -> bool:
    """Check if the message contains the company name (fuzzy).

    Tries: full name, core name (suffix-stripped), domain root,
    and individual tokens from multi-word names.
    """
    name_lower = company_name.lower().strip()
    if name_lower in msg_lower:
        return True

    core = extract_company_core(name_lower)
    if core and core in msg_lower:
        return True

    # For multi-word cores, try each word >= 4 chars
    if " " in core:
        for token in core.split():
            if len(token) >= 4 and token in msg_lower:
                return True

    return False
