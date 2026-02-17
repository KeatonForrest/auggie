"""PEA prompt selector — chooses example mode and relevant examples based on prospect context."""

import logging
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

# Example indices within each file (used for selective injection)
_FULL_EXAMPLE_TAGS = {
    "hr_tech": "Example 1: HR Tech",
    "plg": "Example 2: Product / PLG",
    "msp": "Example 3: MSP Break-Fix",
    "construction": "Example 4: Construction Tech",
    "govtech": "Example 5: Government / GovTech",
    "dev_tooling": "Example 6: Dev Tooling / API Platform",
}

_PARTIAL_EXAMPLE_TAGS = {
    "single_signal": "Example 41: Single Signal",
    "timing_hedge": "Example 42: Timing-Based Hedge",
    "industry_pressure": "Example 43: Industry Pressure",
    "role_hire": "Example 44: Role Hire Without Context",
    "stale_signal": "Example 45: Stale Signal",
    "funding_stage": "Example 46: Inferred Pain From Funding Stage",
    "stack_presence": "Example 47: Dev Tooling Adoption",
}


def _load_prompt_file(filename: str) -> str:
    """Load a prompt file with fail-soft fallback."""
    path = _PROMPTS_DIR / filename
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        logger.warning("Failed to load prompt file: %s", path)
        return ""


def _extract_examples(content: str, tag_prefix: str, count: int = 3) -> list[str]:
    """Extract individual examples from a prompt file by splitting on '---' delimiters."""
    # Split on horizontal rules between examples
    blocks = re.split(r"\n---\n", content)
    examples = []
    for block in blocks:
        block = block.strip()
        if block and "Email 1" in block:
            examples.append(block)
    return examples[:count] if len(examples) > count else examples


def select_examples(
    opportunity_score: Optional[int] = None,
    product_type: str = "saas",
    seller_product_category: str = "",
) -> dict:
    """Select prompt mode and relevant examples based on prospect context.

    Returns:
        {
            "mode": "full" | "partial",
            "examples": list[str],  # 2-3 selected example blocks
            "examples_count": int,
        }
    """
    score = opportunity_score if opportunity_score is not None else 50

    # Determine mode
    if score < 50:
        mode = "partial"
        content = _load_prompt_file("pea_examples_partial.md")
    else:
        mode = "full"
        content = _load_prompt_file("pea_examples_full.md")

    all_examples = _extract_examples(content, mode)

    # Select 2-3 relevant examples based on context
    selected = []

    if product_type == "msp" and mode == "full":
        # Prioritize MSP example
        for ex in all_examples:
            if "MSP" in ex or "managed IT" in ex.lower() or "law firm" in ex.lower():
                selected.append(ex)
                break

    # Add examples relevant to seller category if provided
    category_lower = seller_product_category.lower()
    if category_lower and not selected:
        for ex in all_examples:
            ex_lower = ex.lower()
            if category_lower in ex_lower or any(
                kw in ex_lower for kw in category_lower.split()
            ):
                if ex not in selected:
                    selected.append(ex)
                if len(selected) >= 2:
                    break

    # Fill remaining slots with the first available examples
    for ex in all_examples:
        if ex not in selected:
            selected.append(ex)
        if len(selected) >= 3:
            break

    return {
        "mode": mode,
        "examples": selected,
        "examples_count": len(selected),
    }


def load_prompt_sections(
    opportunity_score: Optional[int] = None,
    product_type: str = "saas",
    seller_product_category: str = "",
    use_selector: bool = False,
) -> dict:
    """Load all prompt sections, optionally using the selector for examples.

    Returns dict with keys: rules_core, subject_rules, examples, mode, examples_count.
    """
    rules_core = _load_prompt_file("pea_rules_core.md")
    subject_rules = _load_prompt_file("pea_subject_rules.md")

    if use_selector:
        selection = select_examples(
            opportunity_score=opportunity_score,
            product_type=product_type,
            seller_product_category=seller_product_category,
        )
        examples_text = "\n\n---\n\n".join(selection["examples"])
        mode = selection["mode"]
        examples_count = selection["examples_count"]
    else:
        # Default: load full or partial based on score (existing behavior)
        score = opportunity_score if opportunity_score is not None else 50
        if score < 50:
            header = (
                "**PARTIAL-SIGNAL PVP EXAMPLES**\n\n"
                "The following examples show how to write valuable sequences "
                "when data is incomplete.\n\n---\n\n"
            )
            examples_text = header + _load_prompt_file("pea_examples_partial.md")
            mode = "partial"
        else:
            header = (
                "**ADDITIONAL PVP EXAMPLES**\n\n"
                "The following examples show the PEA framework in action.\n\n"
                "**SECTION A: FULL-CONFIDENCE PVP EXAMPLES**\n\n"
            )
            full = _load_prompt_file("pea_examples_full.md")
            partial = _load_prompt_file("pea_examples_partial.md")
            examples_text = header + full + "\n\n---\n\n" + partial
            mode = "full"
        examples_count = len(_extract_examples(examples_text, mode))

    return {
        "rules_core": rules_core,
        "subject_rules": subject_rules,
        "examples": examples_text,
        "mode": mode,
        "examples_count": examples_count,
    }
