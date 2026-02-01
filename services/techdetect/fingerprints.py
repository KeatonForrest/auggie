"""Load and normalize technologies.json into immutable data structures."""

import json
import os
from dataclasses import dataclass, field
from services.techdetect.patterns import PreparedPattern, prepare_pattern

_DEFAULT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "technologies.json")


@dataclass(frozen=True)
class Technology:
    name: str
    cats: tuple[int, ...] = ()
    url_patterns: tuple[PreparedPattern, ...] = ()
    header_patterns: tuple[tuple[str, PreparedPattern], ...] = ()  # (header_name, pattern)
    script_patterns: tuple[PreparedPattern, ...] = ()
    meta_patterns: tuple[tuple[str, PreparedPattern], ...] = ()  # (meta_name, pattern)
    html_patterns: tuple[PreparedPattern, ...] = ()
    implies: tuple[str, ...] = ()


def _coerce_to_list(val) -> list:
    if isinstance(val, str):
        return [val]
    if isinstance(val, list):
        return val
    if isinstance(val, dict):
        return list(val.items()) if val else []
    return []


def _coerce_dict(val) -> dict:
    if isinstance(val, dict):
        return val
    if isinstance(val, str):
        return {val: ""}
    return {}


def load_fingerprints(path: str | None = None) -> tuple[dict[str, Technology], dict[str, str]]:
    """Load technologies.json and return (technologies, categories)."""
    fp_path = os.environ.get("TECHDETECT_FINGERPRINTS_PATH") or path or _DEFAULT_PATH
    with open(fp_path) as f:
        data = json.load(f)

    categories = {}
    for cat_id, cat_info in data.get("categories", {}).items():
        categories[cat_id] = cat_info.get("name", f"Category {cat_id}")

    technologies = {}
    for name, attrs in data.get("technologies", {}).items():
        # URL patterns
        url_patterns = tuple(prepare_pattern(p) for p in _coerce_to_list(attrs.get("url", [])))

        # Header patterns: dict of header_name -> pattern(s)
        header_patterns = []
        for hdr, pats in _coerce_dict(attrs.get("headers", {})).items():
            for p in _coerce_to_list(pats):
                header_patterns.append((hdr.lower(), prepare_pattern(p)))

        # Script patterns
        script_patterns = tuple(prepare_pattern(p) for p in _coerce_to_list(attrs.get("scripts", [])))

        # Meta patterns: dict of meta_name -> pattern(s)
        meta_pats = []
        for meta_name, pats in _coerce_dict(attrs.get("meta", {})).items():
            for p in _coerce_to_list(pats):
                meta_pats.append((meta_name.lower(), prepare_pattern(p)))

        # HTML patterns
        html_patterns = tuple(prepare_pattern(p) for p in _coerce_to_list(attrs.get("html", [])))

        # Implies
        implies = tuple(_coerce_to_list(attrs.get("implies", [])))

        # Categories
        cats = tuple(attrs.get("cats", []))

        technologies[name] = Technology(
            name=name,
            cats=cats,
            url_patterns=url_patterns,
            header_patterns=tuple(header_patterns),
            script_patterns=script_patterns,
            meta_patterns=tuple(meta_pats),
            html_patterns=html_patterns,
            implies=implies,
        )

    return technologies, categories
