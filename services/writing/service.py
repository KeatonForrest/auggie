"""service.py - WritingService orchestrator for AI-powered outreach generation."""

import asyncio
import logging
import re
import time
from openai import AsyncOpenAI
from typing import Optional

from models import ResearchDocument
from config import get_settings
from services.writing.types import (
    GenerationContext, ValidationResult, GenerationTelemetry,
    WORD_LIMITS, LINKEDIN_WORD_LIMITS,
    _CATEGORY_KEYWORDS, _CATEGORY_DENYLISTS,
)
from services.writing.postprocess import postprocess, trim_to_word_limit, extract_company_core
from services.writing.email import EmailStrategy
from services.writing.linkedin_dm import LinkedInDMStrategy
from services.writing.linkedin_connection import LinkedInConnectionStrategy
from services.writing.linkedin_shared import filter_relevance, parse_linkedin_output

logger = logging.getLogger(__name__)


class SequenceValidationError(Exception):
    """Raised when a generated sequence fails validation after all repair attempts."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class WritingService:
    """Orchestrator for generating outreach emails and LinkedIn messages.

    Delegates prompt building, parsing, and validation to channel strategies.
    Owns all LLM calls, retry loops, and telemetry.
    """

    def __init__(self):
        self.settings = get_settings()
        self.client = AsyncOpenAI(
            api_key=self.settings.openrouter_api_key,
            base_url="https://openrouter.ai/api/v1",
            timeout=60.0,
        )
        # Strategy instances
        self._email = EmailStrategy()
        self._linkedin_dm = LinkedInDMStrategy()
        self._linkedin_cr = LinkedInConnectionStrategy()

    # ------------------------------------------------------------------
    # Per-channel model resolution
    # ------------------------------------------------------------------

    def _get_model(self, channel: str) -> str:
        """Resolve per-channel model with fallback to writing_model."""
        channel_key = f"writing_model_{channel}"
        model = getattr(self.settings, channel_key, "")
        if model:
            return model
        return self.settings.writing_model

    # ------------------------------------------------------------------
    # LLM call wrapper
    # ------------------------------------------------------------------

    async def _llm_call(self, model: str, messages: list[dict], max_tokens: int) -> tuple[str, int, int]:
        """Single LLM call. Returns (content, input_tokens, output_tokens).

        Applies postprocess() to content automatically.
        """
        response = await self.client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=messages,
        )
        content = response.choices[0].message.content or ""
        content = postprocess(content)

        input_tokens = getattr(response.usage, "prompt_tokens", 0) if response.usage else 0
        output_tokens = getattr(response.usage, "completion_tokens", 0) if response.usage else 0

        return content, input_tokens, output_tokens

    # ------------------------------------------------------------------
    # Telemetry
    # ------------------------------------------------------------------

    def _emit_telemetry(self, tel: GenerationTelemetry) -> None:
        """Emit structured telemetry as a log entry."""
        extra = {
            "channel": tel.channel,
            "model": tel.model,
            "latency_ms": tel.latency_ms,
            "retry_count": tel.retry_count,
            "input_tokens": tel.input_tokens,
            "output_tokens": tel.output_tokens,
            "parse_success": tel.parse_success,
            "repair_attempted": tel.repair_attempted,
            "repair_success": tel.repair_success,
            "word_limit_pass": tel.word_limit_pass,
            "cta_rescued": tel.cta_rescued,
            "relevance_reprompted": tel.relevance_reprompted,
        }
        if tel.validation_fail_reason:
            extra["validation_fail_reason"] = tel.validation_fail_reason
        logger.info(f"{tel.channel} generation", extra=extra)

    # ------------------------------------------------------------------
    # Report building (shared across channels)
    # ------------------------------------------------------------------

    def _build_report(self, document: ResearchDocument, product_context: str, retrieved_materials: str = "",
                       seller_company: str = "", problems_solved: str = "", persona_context: str = "",
                       custom_signals: str = "") -> str:
        """Build the report content from research document."""
        sections = []

        sections.append(f"# Research Report: {document.company_name}")
        sections.append("")

        sections.append("## Company Overview")
        sections.append(document.company_overview)
        sections.append("")

        if document.business_problems:
            sections.append("## Business Problems & Pain Points")
            sections.append(document.business_problems)
            sections.append("")

        if document.existential_data_points:
            sections.append("## Existential Data Points (Urgency Signals)")
            sections.append(document.existential_data_points)
            sections.append("")

        if document.before_scenario:
            sections.append("## Before Scenario (Problems → Consequences → Current Attempts)")
            sections.append(document.before_scenario)
            sections.append("")

        if document.pvp_seed:
            sections.append("## PVP Seed (Key Insight for Outreach)")
            sections.append(document.pvp_seed)
            sections.append("")

        if document.projects_initiatives:
            sections.append("## Current Projects & Initiatives")
            sections.append(document.projects_initiatives)
            sections.append("")

        if document.product_fit:
            sections.append("## Product Fit Analysis")
            sections.append(document.product_fit)
            sections.append("")

        if document.talking_points:
            sections.append("## Recommended Talking Points")
            sections.append(document.talking_points)
            sections.append("")

        if document.key_contacts:
            sections.append("## Key Contacts")
            sections.append(document.key_contacts)
            sections.append("")

        if document.recommended_contacts:
            sections.append("## Recommended Contacts")
            sections.append(document.recommended_contacts)
            sections.append("")

        if persona_context:
            sections.append("## Target Contact")
            sections.append(persona_context)
            sections.append("")

        sections.append("## Our Product (What We're Selling)")
        if seller_company:
            sections.append(f"**Company:** {seller_company}")
        sections.append(product_context)

        if problems_solved:
            sections.append("")
            sections.append("## Specific Problems We Solve")
            sections.append(f"Align email angles to these problems when the research shows a match: {problems_solved}")

        if custom_signals:
            sections.append("")
            sections.append("## Custom Signals to Emphasize")
            sections.append(f"If the research mentions any of these, use them as email hooks: {custom_signals}")

        if retrieved_materials:
            sections.append("")
            sections.append("## Sales Materials (Case Studies, Battle Cards, Proof Points)")
            sections.append("Use these to reference specific results, metrics, and customer stories in your emails.")
            sections.append(retrieved_materials)

        return "\n".join(sections)

    # ------------------------------------------------------------------
    # Product category detection and relevance gate (shared)
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_product_category(product_context: str) -> str:
        """Detect seller product category from product context using keyword hits.

        Returns the category with >= 2 keyword hits, or "" if none match.
        """
        if not product_context:
            return ""
        text = product_context.lower()
        for category, keywords in _CATEGORY_KEYWORDS.items():
            hits = sum(1 for kw in keywords if kw in text)
            if hits >= 2:
                return category
        return ""

    @staticmethod
    def _score_hook_relevance(text: str, category: str) -> int:
        """Score a talking-point bullet for product relevance.

        Returns 5 (pass), 4 (blocked but linked), or 2 (blocked, no linkage).
        """
        if category not in _CATEGORY_DENYLISTS:
            return 5
        denylist = _CATEGORY_DENYLISTS[category]
        lower = text.lower()
        has_blocked = any(pat in lower for pat in denylist["blocked_patterns"])
        if not has_blocked:
            return 5
        has_linkage = any(ov in lower for ov in denylist["linkage_overrides"])
        return 4 if has_linkage else 2

    def _apply_relevance_gate(self, report: str, category: str) -> str:
        """Filter irrelevant talking-point bullets from the report."""
        if category not in _CATEGORY_DENYLISTS:
            return report

        header = "## Recommended Talking Points"
        header_idx = report.find(header)
        if header_idx == -1:
            return report

        section_start = header_idx + len(header)
        next_section = report.find("\n## ", section_start)
        if next_section == -1:
            section_end = len(report)
        else:
            section_end = next_section

        section_text = report[section_start:section_end]
        lines = section_text.split("\n")
        filtered_lines = []
        kept_bullets = 0

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("- ") or stripped.startswith("* "):
                score = self._score_hook_relevance(stripped, category)
                if score >= 4:
                    filtered_lines.append(line)
                    kept_bullets += 1
            else:
                filtered_lines.append(line)

        if kept_bullets == 0:
            filtered_lines.append("")
            filtered_lines.append(
                "**Fallback:** All recommended hooks were filtered as irrelevant "
                "to this product category. Use signals from Business Problems, "
                "Existential Data Points, or Before Scenario sections instead."
            )

        filtered_section = "\n".join(filtered_lines)
        return report[:header_idx] + header + filtered_section + report[section_end:]

    # ------------------------------------------------------------------
    # Email sequence generation
    # ------------------------------------------------------------------

    async def generate_email_sequence(
        self,
        document: ResearchDocument,
        product_context: str,
        product_type: str = "saas",
        retrieved_materials: str = "",
        seller_company: str = "",
        problems_solved: str = "",
        persona_context: str = "",
        custom_signals: str = "",
    ) -> tuple[list[dict], list[str]]:
        """Generate a 3-email sequence from a research document.

        Returns:
            Tuple of (emails list, subject_options list).
        """
        start_time = time.monotonic()
        tel = GenerationTelemetry(channel="email")

        # Build the report from research
        report = self._build_report(
            document, product_context, retrieved_materials,
            seller_company=seller_company, problems_solved=problems_solved,
            persona_context=persona_context, custom_signals=custom_signals,
        )

        # Apply product-relevance gate
        category = ""
        if getattr(self.settings, "writing_relevance_gate_enabled", False):
            category = self._detect_product_category(product_context)
            if category:
                report = self._apply_relevance_gate(report, category)

        # Build generation context
        ctx = GenerationContext(
            document=document,
            product_context=product_context,
            report=report,
            product_type=product_type,
            product_category=category,
            opportunity_score=document.opportunity_score,
            has_persona=bool(persona_context),
            pea_selector_enabled=getattr(self.settings, "pea_selector_enabled", False),
            company_name=document.company_name,
        )

        strategy = self._email
        model = self._get_model("email")
        tel.model = model

        # Build prompts via strategy
        system_prompt = strategy.build_system_prompt(ctx)
        user_prompt = strategy.build_user_prompt(ctx)

        # LLM call
        response, in_tok, out_tok = await self._llm_call(
            model,
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            2000,
        )
        tel.input_tokens += in_tok
        tel.output_tokens += out_tok

        # Parse
        emails, subject_options = strategy.parse_output(response, ctx)
        tel.parse_success = len(emails) > 0

        # Validate -> repair once -> validate
        result = strategy.validate((emails, subject_options), ctx)

        if not result.is_valid:
            tel.repair_attempted = True
            try:
                repair_text = strategy.repair_prompt(response, ctx, result.error_reason)
                repaired_response, in_tok, out_tok = await self._llm_call(
                    model,
                    [{"role": "user", "content": repair_text}],
                    2000,
                )
                tel.input_tokens += in_tok
                tel.output_tokens += out_tok
                emails, subject_options = strategy.parse_output(repaired_response, ctx)
                result = strategy.validate((emails, subject_options), ctx)
                tel.repair_success = result.is_valid
            except Exception:
                logger.warning("Repair pass failed", exc_info=True)

            if not result.is_valid:
                tel.validation_fail_reason = result.error_reason
                tel.latency_ms = int((time.monotonic() - start_time) * 1000)
                self._emit_telemetry(tel)
                raise SequenceValidationError(
                    code="sequence_repair_failed" if tel.repair_attempted else "sequence_validation_failed",
                    message=result.error_reason or "Generated sequence failed validation after repair",
                )

        # Enforce word limits - shorten over-limit emails in parallel
        over = strategy.over_limit_emails(emails)
        if over:
            for _pass in range(2):
                async def _try_shorten(ov: dict) -> tuple[int, str | None]:
                    try:
                        prompt = strategy.shorten_prompt(ov)
                        shortened, _, _ = await self._llm_call(
                            model,
                            [{"role": "user", "content": prompt}],
                            500,
                        )
                        return ov["email_number"], shortened
                    except Exception:
                        logger.warning("Failed to shorten email %d (was %d words, limit %d)",
                                       ov["email_number"], ov["word_count"], ov["limit"])
                        return ov["email_number"], None

                results = await asyncio.gather(*[_try_shorten(ov) for ov in over])
                for email_num, shortened in results:
                    if shortened is not None:
                        for email in emails:
                            if email["email_number"] == email_num:
                                email["body"] = shortened
                                break

                over = strategy.over_limit_emails(emails)
                if not over:
                    break

            # Last-resort hard cap
            for ov in strategy.over_limit_emails(emails):
                for email in emails:
                    if email["email_number"] == ov["email_number"]:
                        email["body"] = trim_to_word_limit(email["body"], ov["limit"])
                        break

            # Re-validate after shortening
            still_over = strategy.over_limit_emails(emails)
            if still_over:
                over_details = ", ".join(
                    f"Email {o['email_number']}: {o['word_count']}/{o['limit']}"
                    for o in still_over
                )
                tel.word_limit_pass = False
                tel.latency_ms = int((time.monotonic() - start_time) * 1000)
                self._emit_telemetry(tel)
                raise SequenceValidationError(
                    code="sequence_validation_failed",
                    message=f"Emails still over word limit after shortening: {over_details}",
                )

        tel.word_limit_pass = True
        tel.latency_ms = int((time.monotonic() - start_time) * 1000)
        self._emit_telemetry(tel)

        return emails, subject_options

    # ------------------------------------------------------------------
    # LinkedIn normalization (word-limit, CTA rescue, char-limit)
    # ------------------------------------------------------------------

    async def _normalize_linkedin(
        self,
        message: str,
        mode: str,
        limit: int,
        model: str,
        tel: GenerationTelemetry,
    ) -> tuple[str, bool]:
        """Trim to word/char limits with CTA rescue. Returns (message, cta_rescued)."""
        cta_rescued = False

        if len(message.split()) > limit:
            message = trim_to_word_limit(message, limit)

            # CTA rescue: if trim killed trailing ?
            if not re.search(r'\?\s*$', message):
                rescue_prompt = (
                    f"Rewrite this LinkedIn message to be under {limit} words. "
                    "It MUST end with a question. Keep the same message and tone. "
                    f"Output ONLY the message text.\n\n{message}"
                )
                try:
                    rescue_raw, in_tok, out_tok = await self._llm_call(
                        model,
                        [{"role": "user", "content": rescue_prompt}],
                        500,
                    )
                    tel.input_tokens += in_tok
                    tel.output_tokens += out_tok
                    rescue_msg = rescue_raw.strip()
                    if (
                        rescue_msg
                        and len(rescue_msg.split()) <= limit
                        and re.search(r'\?\s*$', rescue_msg)
                    ):
                        message = rescue_msg
                        cta_rescued = True
                except Exception:
                    logger.warning("CTA rescue failed for LinkedIn message")

        # Char-limit normalization (connection_request only)
        if mode == "connection_request" and len(message) > 300:
            truncated = message[:300]
            last_period = max(truncated.rfind('.'), truncated.rfind('?'), truncated.rfind('!'))
            if last_period > 100:
                message = message[:last_period + 1].strip()
            else:
                message = truncated.strip()

            # CTA rescue if truncation removed ?
            if not re.search(r'\?\s*$', message):
                rescue_prompt = (
                    f"Rewrite this LinkedIn connection request note to be under 300 characters "
                    f"and under {limit} words. It MUST end with a question. "
                    f"Keep the same message and tone. Output ONLY the message text.\n\n{message}"
                )
                try:
                    rescue_raw, in_tok, out_tok = await self._llm_call(
                        model,
                        [{"role": "user", "content": rescue_prompt}],
                        300,
                    )
                    tel.input_tokens += in_tok
                    tel.output_tokens += out_tok
                    rescue_msg = rescue_raw.strip()
                    if (
                        rescue_msg
                        and len(rescue_msg) <= 300
                        and re.search(r'\?\s*$', rescue_msg)
                    ):
                        message = rescue_msg
                        cta_rescued = True
                except Exception:
                    logger.warning("Char-limit CTA rescue failed for connection request")

        return message, cta_rescued

    # ------------------------------------------------------------------
    # LinkedIn message generation
    # ------------------------------------------------------------------

    async def generate_linkedin_message(
        self,
        document: ResearchDocument,
        product_context: str,
        linkedin_context: dict,
        mode: str = "dm",
        retrieved_materials: str = "",
        seller_company: str = "",
        problems_solved: str = "",
        persona_context: str = "",
        custom_signals: str = "",
    ) -> dict:
        """Generate a single LinkedIn message from a research document.

        Returns dict with: message, word_count, char_count, content_type, mode, cta_rescued.
        """
        # Validate mode
        if mode not in ("dm", "connection_request"):
            raise ValueError(f"Invalid LinkedIn message mode: {mode!r}. Must be 'dm' or 'connection_request'.")

        start_time = time.monotonic()
        tel = GenerationTelemetry(channel=f"linkedin_{mode}")

        # Select strategy
        strategy = self._linkedin_dm if mode == "dm" else self._linkedin_cr

        # Build report
        report = self._build_report(
            document, product_context, retrieved_materials,
            seller_company=seller_company, problems_solved=problems_solved,
            persona_context=persona_context, custom_signals=custom_signals,
        )

        # Detect category (used for relevance gate + filter + prompt constraint)
        category = self._detect_product_category(product_context)

        # Apply relevance gate if enabled
        if getattr(self.settings, "writing_relevance_gate_enabled", False):
            if category:
                report = self._apply_relevance_gate(report, category)

        # Build generation context
        ctx = GenerationContext(
            document=document,
            product_context=product_context,
            report=report,
            mode=mode,
            linkedin_context=linkedin_context,
            persona_context=persona_context,
            problems_solved=problems_solved,
            company_name=document.company_name,
            product_category=category,
        )

        # Map mode to config key: "dm" → "linkedin_dm", "connection_request" → "linkedin_connection"
        config_channel = "linkedin_dm" if mode == "dm" else "linkedin_connection"
        model = self._get_model(config_channel)
        tel.model = model

        # Build prompts via strategy
        system_prompt = strategy.build_system_prompt(ctx)
        user_prompt = strategy.build_user_prompt(ctx)

        # LLM call
        raw, in_tok, out_tok = await self._llm_call(
            model,
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            500,
        )
        tel.input_tokens += in_tok
        tel.output_tokens += out_tok

        # Parse
        message = strategy.parse_output(raw, ctx)

        if not message:
            tel.latency_ms = int((time.monotonic() - start_time) * 1000)
            self._emit_telemetry(tel)
            raise SequenceValidationError(
                code="linkedin_generation_failed",
                message="Generated LinkedIn message was empty",
            )

        # Relevance post-filter: single re-prompt if blocked terms found
        is_clean, blocked_terms = filter_relevance(message, category)
        if not is_clean:
            tel.relevance_reprompted = True
            reprompt = (
                f"Your message references {', '.join(blocked_terms)}. "
                "This is not relevant to what the seller sells. "
                "Rewrite using only signals from the research report that connect to: "
                f"{problems_solved}\n\n"
                "Output ONLY the message text. No headers or labels."
            )
            retry_raw, in_tok, out_tok = await self._llm_call(
                model,
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                    {"role": "assistant", "content": f"Message:\n{message}"},
                    {"role": "user", "content": reprompt},
                ],
                500,
            )
            tel.input_tokens += in_tok
            tel.output_tokens += out_tok
            retry_msg = parse_linkedin_output(retry_raw)
            if retry_msg:
                message = retry_msg

        # Normalize: word-limit trim, CTA rescue, char-limit trim (CR only)
        limit = LINKEDIN_WORD_LIMITS[mode]
        cta_rescued = False
        message, cta_rescued = await self._normalize_linkedin(
            message, mode, limit, model, tel
        )

        # Quality gate - validate via strategy
        val_ctx = GenerationContext(
            document=document,
            product_context=product_context,
            report=report,
            mode=mode,
            company_name=document.company_name,
        )
        result = strategy.validate(message, val_ctx)

        # One retry on anchor failure
        if not result.is_valid and "anchor" in result.error_reason:
            core = extract_company_core(document.company_name)
            anchor_rescue_prompt = (
                f'Your message does not mention the prospect company. '
                f'Rewrite it to include "{core}" naturally. '
                f'Keep the same tone and structure. It MUST end with a question.\n\n'
                f'Output ONLY the message text.\n\n{message}'
            )
            try:
                anchor_raw, in_tok, out_tok = await self._llm_call(
                    model,
                    [{"role": "user", "content": anchor_rescue_prompt}],
                    500,
                )
                tel.input_tokens += in_tok
                tel.output_tokens += out_tok
                anchor_msg = parse_linkedin_output(anchor_raw)
                if anchor_msg:
                    message = anchor_msg

                    # Re-run full normalization after anchor rewrite
                    message, anchor_cta = await self._normalize_linkedin(
                        message, mode, limit, model, tel
                    )
                    cta_rescued = cta_rescued or anchor_cta

                    result = strategy.validate(message, val_ctx)
            except Exception:
                logger.warning("Anchor rescue retry failed for LinkedIn message")

        if not result.is_valid:
            tel.validation_fail_reason = result.error_reason
            tel.latency_ms = int((time.monotonic() - start_time) * 1000)
            self._emit_telemetry(tel)
            raise SequenceValidationError(
                code="linkedin_validation_failed",
                message=result.error_reason,
            )

        tel.cta_rescued = cta_rescued
        tel.word_limit_pass = True
        tel.latency_ms = int((time.monotonic() - start_time) * 1000)
        self._emit_telemetry(tel)

        return {
            "message": message,
            "word_count": len(message.split()),
            "char_count": len(message),
            "content_type": linkedin_context.get("content_type", "none"),
            "mode": mode,
            "cta_rescued": cta_rescued,
        }

    # ------------------------------------------------------------------
    # Formatting
    # ------------------------------------------------------------------

    def format_emails_markdown(self, emails: list[dict]) -> str:
        """Format emails as markdown for display."""
        sections = ["# Email Sequence\n"]

        for email in emails:
            sections.append(f"## Email {email['email_number']}")
            sections.append(f"**Subject:** {email['subject']}\n")
            sections.append(email['body'])
            sections.append("\n---\n")

        return "\n".join(sections)
