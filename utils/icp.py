"""ICP utilities shared across routes and services."""

from __future__ import annotations


# Buyer company verticals (multi-select — describes who the seller sells TO)
BUYER_VERTICALS: list[str] = [
    "Financial Services",
    "Healthcare",
    "Construction",
    "Education",
    "Real Estate",
    "Insurance",
    "Legal",
    "Technology",
    "Retail / E-commerce",
    "Manufacturing",
    "Professional Services",
    "Media / Entertainment",
    "Logistics / Supply Chain",
    "Energy / Utilities",
    "Telecommunications",
    "Government / Public Sector",
    "Travel / Hospitality",
]


# Map legacy labels → current buyer-vertical taxonomy.
# Handles both the original v1 industry labels AND the brief v2 tech-category
# labels that were incorrectly stored in target_industries.
LEGACY_VERTICAL_MAP: dict[str, str] = {
    # v1 legacy industry labels
    "SaaS / Software": "Technology",
    "Fintech / Financial Services": "Financial Services",
    "Healthcare / Life Sciences": "Healthcare",
    "E-commerce / Retail": "Retail / E-commerce",
    "Education / EdTech": "Education",
    "Real Estate / PropTech": "Real Estate",
    "Logistics / Supply Chain": "Logistics / Supply Chain",
    "Energy / Utilities": "Energy / Utilities",
    "Media / Entertainment": "Media / Entertainment",
    "Cybersecurity": "Technology",
    "Travel / Hospitality": "Travel / Hospitality",
    "Government / Public Sector": "Government / Public Sector",
    # v2 tech-category labels (brief window where these were stored in target_industries)
    "Fintech": "Financial Services",
    "HealthTech": "Healthcare",
    "MarTech": "Technology",
    "ConstructionTech": "Construction",
    "EdTech": "Education",
    "PropTech": "Real Estate",
    "InsurTech": "Insurance",
    "LegalTech": "Legal",
    "HRTech": "Professional Services",
    "DevTools / Infra": "Technology",
    "E-commerce Tech": "Retail / E-commerce",
    "Supply Chain / Logistics Tech": "Logistics / Supply Chain",
    "GovTech": "Government / Public Sector",
    "TravelTech": "Travel / Hospitality",
    "MediaTech": "Media / Entertainment",
    "Horizontal / Cross-industry": "Technology",
}


def normalize_verticals(stored: list[str]) -> list[str]:
    """Normalize legacy industry/category labels to buyer-vertical taxonomy.

    Values already in BUYER_VERTICALS pass through unchanged; legacy values
    are mapped via _LEGACY_VERTICAL_MAP. Unknown values are preserved as-is.
    Duplicates are removed while preserving order.
    """
    valid_set = set(BUYER_VERTICALS)
    seen: set[str] = set()
    out: list[str] = []
    for label in stored:
        cleaned = (label or "").strip()
        if not cleaned:
            continue
        mapped = cleaned if cleaned in valid_set else LEGACY_VERTICAL_MAP.get(cleaned, cleaned)
        if mapped not in seen:
            seen.add(mapped)
            out.append(mapped)
    return out
