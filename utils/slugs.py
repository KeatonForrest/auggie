"""Slug generation for vanity URLs."""

import re
import unicodedata


def slugify(name: str, max_length: int = 80) -> str:
    """Convert a company name to a URL-safe slug.

    - Unicode normalization -> ASCII
    - Lowercase
    - Non-alphanumeric -> hyphens
    - Collapse consecutive hyphens
    - Strip leading/trailing hyphens
    - Truncate at word boundary to max_length
    - Fallback to "untitled" for empty/all-special-char names
    """
    # Normalize unicode to ASCII
    text = unicodedata.normalize("NFKD", name)
    text = text.encode("ascii", "ignore").decode("ascii")

    # Lowercase
    text = text.lower()

    # Replace non-alphanumeric with hyphens
    text = re.sub(r"[^a-z0-9]+", "-", text)

    # Collapse consecutive hyphens and strip edges
    text = re.sub(r"-{2,}", "-", text)
    text = text.strip("-")

    # Truncate at word boundary
    if len(text) > max_length:
        text = text[:max_length]
        # Don't cut in the middle of a word — trim back to last hyphen
        last_hyphen = text.rfind("-")
        if last_hyphen > 0:
            text = text[:last_hyphen]

    return text or "untitled"
