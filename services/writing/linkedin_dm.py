"""linkedin_dm.py - LinkedInDMStrategy for direct message generation."""

from services.writing.postprocess import extract_company_core
from services.writing.types import GenerationContext, ValidationResult, LINKEDIN_WORD_LIMITS
from services.writing.linkedin_shared import (
    SHARED_LINKEDIN_RULES,
    build_linkedin_user_prompt,
    parse_linkedin_output,
    validate_linkedin_banned_phrases,
    validate_linkedin_anchor,
    validate_linkedin_question,
)


DM_MODE_BLOCK = """

WORD LIMIT: 50-90 words. Aim for this range. The ceiling is enforced; the floor is a target.

STRUCTURE:
1. Hook (1-2 sentences): Reference something specific -- a post they wrote,
   a career move, a company initiative. Connect it to a business pattern.
2. Bridge (1 sentence): Why this matters now / what you've seen at
   similar companies.
3. CTA (1 sentence): A genuine question that invites a reply."""


class LinkedInDMStrategy:
    """Pure-logic strategy for LinkedIn direct messages."""

    def build_system_prompt(self, ctx: GenerationContext) -> str:
        return SHARED_LINKEDIN_RULES + DM_MODE_BLOCK

    def build_user_prompt(self, ctx: GenerationContext) -> str:
        return build_linkedin_user_prompt(ctx)

    def parse_output(self, raw: str, ctx: GenerationContext) -> str:
        return parse_linkedin_output(raw)

    def validate(self, output: str, ctx: GenerationContext) -> ValidationResult:
        """Validate a LinkedIn DM meets structural quality requirements."""
        message = output

        # Trailing question check
        ok, reason = validate_linkedin_question(message)
        if not ok:
            return ValidationResult(is_valid=False, error_reason=reason)

        # Word count check
        word_count = len(message.split())
        if word_count < 10:
            return ValidationResult(is_valid=False, error_reason=f"Message is {word_count} words, minimum is 10")
        limit = LINKEDIN_WORD_LIMITS["dm"]
        if word_count > limit + 10:
            return ValidationResult(is_valid=False, error_reason=f"Message is {word_count} words, limit is {limit}")

        # Banned phrases
        msg_lower = message.lower()
        ok, reason = validate_linkedin_banned_phrases(msg_lower)
        if not ok:
            return ValidationResult(is_valid=False, error_reason=reason)

        # Company anchor
        ok, reason = validate_linkedin_anchor(msg_lower, ctx.company_name)
        if not ok:
            return ValidationResult(is_valid=False, error_reason=reason)

        return ValidationResult(is_valid=True)

    def repair_prompt(self, raw: str, ctx: GenerationContext, reason: str) -> str:
        """Return a repair prompt based on the failure reason."""
        limit = LINKEDIN_WORD_LIMITS["dm"]

        if "anchor" in reason:
            core = extract_company_core(ctx.company_name)
            return (
                f'Your message does not mention the prospect company. '
                f'Rewrite it to include "{core}" naturally. '
                f'Keep the same tone and structure. It MUST end with a question.\n\n'
                f'Output ONLY the message text.\n\n{raw}'
            )

        if "relevance" in reason:
            return (
                f"Your message references off-topic signals. "
                "Rewrite using only signals from the research report that connect to "
                f"what the seller sells.\n\n"
                "Output ONLY the message text. No headers or labels."
            )

        # CTA rescue (default)
        return (
            f"Rewrite this LinkedIn message to be under {limit} words. "
            "It MUST end with a question. Keep the same message and tone. "
            f"Output ONLY the message text.\n\n{raw}"
        )

    def limits(self) -> dict:
        return {"word_limit": LINKEDIN_WORD_LIMITS["dm"]}
