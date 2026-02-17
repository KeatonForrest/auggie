"""linkedin_connection.py - LinkedInConnectionStrategy for connection request notes."""

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


CR_MODE_BLOCK = """

WORD LIMIT: 25-45 words. Aim for this range. The ceiling is enforced;
the floor is a target. Connection request notes are capped at 300
characters by LinkedIn -- every word counts.

STRUCTURE:
1. Context (1 sentence): One specific, concrete reason you're reaching out.
2. CTA (1 sentence): A genuine question that invites them to accept.

No bridge sentence. There is no room. Get to the point."""


class LinkedInConnectionStrategy:
    """Pure-logic strategy for LinkedIn connection request notes."""

    def build_system_prompt(self, ctx: GenerationContext) -> str:
        return SHARED_LINKEDIN_RULES + CR_MODE_BLOCK

    def build_user_prompt(self, ctx: GenerationContext) -> str:
        return build_linkedin_user_prompt(ctx)

    def parse_output(self, raw: str, ctx: GenerationContext) -> str:
        return parse_linkedin_output(raw)

    def validate(self, output: str, ctx: GenerationContext) -> ValidationResult:
        """Validate a LinkedIn connection request note meets requirements."""
        message = output

        # Trailing question check
        ok, reason = validate_linkedin_question(message)
        if not ok:
            return ValidationResult(is_valid=False, error_reason=reason)

        # Word count check
        word_count = len(message.split())
        if word_count < 10:
            return ValidationResult(is_valid=False, error_reason=f"Message is {word_count} words, minimum is 10")
        limit = LINKEDIN_WORD_LIMITS["connection_request"]
        if word_count > limit:
            return ValidationResult(is_valid=False, error_reason=f"Message is {word_count} words, limit is {limit}")

        # Char limit
        if len(message) > 300:
            return ValidationResult(is_valid=False, error_reason="Connection request exceeds 300 character limit")

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
        limit = LINKEDIN_WORD_LIMITS["connection_request"]

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

        # CTA rescue (default) - includes char limit
        return (
            f"Rewrite this LinkedIn connection request note to be under 300 characters "
            f"and under {limit} words. It MUST end with a question. "
            f"Keep the same message and tone. Output ONLY the message text.\n\n{raw}"
        )

    def limits(self) -> dict:
        return {"word_limit": LINKEDIN_WORD_LIMITS["connection_request"], "char_limit": 300}
