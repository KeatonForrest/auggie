"""Shared utilities used across route modules."""

import logging
import re

from fastapi.templating import Jinja2Templates

from config import get_settings
from services.materials import MaterialsService

logger = logging.getLogger(__name__)
settings = get_settings()
templates = Jinja2Templates(directory="templates")

# Lazy-initialized materials service
materials_service = None


def get_materials_service():
    """Get or create materials service (lazy init)."""
    global materials_service
    if materials_service is None and settings.materials_enabled:
        materials_service = MaterialsService()
    return materials_service


def normalize_url(url: str) -> str:
    """Add https:// if no protocol specified. For non-research URLs."""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def parse_personas_string(personas_str: str) -> tuple[list[str], list[str]]:
    """Parse stored personas string back into levels and functions lists."""
    levels = []
    functions = []
    if not personas_str:
        return levels, functions

    # Format: "Levels: VP, Director | Functions: Sales / Revenue, Marketing"
    parts = personas_str.split(" | ")
    for part in parts:
        if part.startswith("Levels: "):
            levels = [l.strip() for l in part[8:].split(", ")]
        elif part.startswith("Functions: "):
            functions = [f.strip() for f in part[11:].split(", ")]

    return levels, functions


def _build_target_titles(user: dict) -> list[str]:
    """Build a list of target job titles from user's ICP settings."""
    levels, functions = parse_personas_string(user.get("target_personas") or "")

    title_map = {
        "C-Suite": {"Sales / Revenue": "CRO", "Marketing": "CMO", "Engineering / Product": "CTO",
                     "Finance / Accounting": "CFO", "Operations": "COO", "IT / Security": "CISO",
                     "HR / People": "CHRO", "Customer Success": "CCO", "Legal": "General Counsel"},
        "VP": {"Sales / Revenue": "VP Sales", "Marketing": "VP Marketing", "Engineering / Product": "VP Engineering",
               "Finance / Accounting": "VP Finance", "Operations": "VP Operations", "IT / Security": "VP IT",
               "HR / People": "VP People", "Customer Success": "VP Customer Success", "Legal": "VP Legal"},
        "Director": {"Sales / Revenue": "Director of Sales", "Marketing": "Director of Marketing",
                     "Engineering / Product": "Director of Engineering", "Finance / Accounting": "Director of Finance",
                     "Operations": "Director of Operations", "IT / Security": "Director of IT",
                     "HR / People": "Director of HR", "Customer Success": "Director of Customer Success"},
    }

    titles = []
    for level in levels:
        if level in title_map:
            for func in functions:
                if func in title_map[level]:
                    titles.append(title_map[level][func])

    if not titles:
        titles = ["CTO", "VP Engineering", "VP Sales", "CEO"]

    return titles[:5]
