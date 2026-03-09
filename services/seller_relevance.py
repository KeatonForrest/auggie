"""Shared seller-relevance helpers for filtering noisy research context."""

from __future__ import annotations

import re
from typing import Optional

from services.writing.types import _CATEGORY_DENYLISTS, normalize_seller_category


_CATEGORY_ALIASES = {
    "security": "cybersecurity",
}


def resolve_seller_category(raw: str) -> str:
    """Normalize a seller category string to a denylist-aware slug."""
    if not raw:
        return ""

    normalized = normalize_seller_category(raw)
    if normalized:
        return normalized

    lowered = raw.strip().lower()
    lowered = _CATEGORY_ALIASES.get(lowered, lowered)
    if lowered in _CATEGORY_DENYLISTS:
        return lowered
    return ""


def is_text_relevant(text: str, seller_category: str) -> bool:
    """Return True when a text block is relevant for the seller category."""
    if not text:
        return True

    category = resolve_seller_category(seller_category)
    if not category or category not in _CATEGORY_DENYLISTS:
        return True

    denylist = _CATEGORY_DENYLISTS[category]
    text_lower = text.lower()
    has_blocked = any(pattern in text_lower for pattern in denylist["blocked_patterns"])
    if not has_blocked:
        return True

    return any(override in text_lower for override in denylist["linkage_overrides"])


def filter_text_blocks(text: str, seller_category: str) -> str:
    """Keep only seller-relevant blocks from a noisy text blob."""
    if not text:
        return text

    category = resolve_seller_category(seller_category)
    if not category or category not in _CATEGORY_DENYLISTS:
        return text

    blocks = _split_text_blocks(text)
    kept = [block for block in blocks if is_text_relevant(block, category)]
    if not kept:
        return ""

    separator = "\n\n" if "\n\n" in text else "\n"
    return separator.join(kept)


def filter_text_items(items: list[str], seller_category: str) -> list[str]:
    """Keep only seller-relevant strings from a structured list."""
    if not items:
        return []
    return [item for item in items if is_text_relevant(item, seller_category)]


def _split_text_blocks(text: str) -> list[str]:
    """Split text into paragraphs first, then fall back to non-empty lines."""
    paragraphs = [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]
    if len(paragraphs) > 1:
        return paragraphs
    return [line.strip() for line in text.splitlines() if line.strip()]
