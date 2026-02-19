"""Persona parsing and normalization helpers."""

from __future__ import annotations


def parse_personas_string(personas_str: str) -> tuple[list[str], list[str]]:
    """Parse stored personas string back into levels and functions lists."""
    levels: list[str] = []
    functions: list[str] = []
    if not personas_str:
        return levels, functions

    # Format: "Levels: VP, Director | Functions: Sales / Revenue, Marketing"
    parts = personas_str.split(" | ")
    for part in parts:
        if part.startswith("Levels: "):
            levels = [l.strip() for l in part[8:].split(", ") if l.strip()]
        elif part.startswith("Functions: "):
            functions = [f.strip() for f in part[11:].split(", ") if f.strip()]

    return levels, functions


def build_target_titles(personas_str: str, *, max_titles: int = 5) -> list[str]:
    """Build a list of target job titles from persona settings or raw titles.

    Accepts either:
    - Stored structured string: "Levels: ... | Functions: ..."
    - A comma-separated list of titles: "CTO, VP Engineering"
    - A single title: "CTO"
    """
    raw = (personas_str or "").strip()
    if not raw:
        return ["CTO", "VP Engineering", "VP Sales", "CEO"][:max_titles]

    levels, functions = parse_personas_string(raw)

    title_map: dict[str, dict[str, str]] = {
        "C-Suite": {
            "Sales / Revenue": "CRO",
            "Marketing": "CMO",
            "Engineering / Product": "CTO",
            "Finance / Accounting": "CFO",
            "Operations": "COO",
            "IT / Security": "CISO",
            "HR / People": "CHRO",
            "Customer Success": "CCO",
            "Data Science / BI": "Chief Data Officer",
            "Legal": "General Counsel",
        },
        "VP": {
            "Sales / Revenue": "VP Sales",
            "Marketing": "VP Marketing",
            "Engineering / Product": "VP Engineering",
            "Finance / Accounting": "VP Finance",
            "Operations": "VP Operations",
            "IT / Security": "VP IT",
            "HR / People": "VP People",
            "Customer Success": "VP Customer Success",
            "Data Science / BI": "VP Data",
            "Legal": "VP Legal",
        },
        "Director": {
            "Sales / Revenue": "Director of Sales",
            "Marketing": "Director of Marketing",
            "Engineering / Product": "Director of Engineering",
            "Finance / Accounting": "Director of Finance",
            "Operations": "Director of Operations",
            "IT / Security": "Director of IT",
            "HR / People": "Director of HR",
            "Customer Success": "Director of Customer Success",
            "Data Science / BI": "Director of Analytics",
        },
    }

    titles: list[str] = []
    if levels and functions:
        for level in levels:
            mapping = title_map.get(level)
            if not mapping:
                continue
            for func in functions:
                mapped = mapping.get(func)
                if mapped:
                    titles.append(mapped)

    if not titles and "Levels:" not in raw and "Functions:" not in raw:
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        titles = parts if parts else [raw]

    if not titles:
        titles = ["CTO", "VP Engineering", "VP Sales", "CEO"]

    seen: set[str] = set()
    out: list[str] = []
    for t in titles:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out[:max_titles]

