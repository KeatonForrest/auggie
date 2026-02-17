"""base.py - ChannelStrategy protocol for writing strategies."""

from typing import Any, Protocol

from services.writing.types import GenerationContext, ValidationResult


class ChannelStrategy(Protocol):
    """Structural typing protocol for channel strategies.

    Strategies are pure logic - no LLM client, no I/O.
    WritingService owns all LLM calls.
    """

    def build_system_prompt(self, ctx: GenerationContext) -> str: ...
    def build_user_prompt(self, ctx: GenerationContext) -> str: ...
    def parse_output(self, raw: str, ctx: GenerationContext) -> Any: ...
    def validate(self, output: Any, ctx: GenerationContext) -> ValidationResult: ...
    def repair_prompt(self, raw: str, ctx: GenerationContext, reason: str) -> str: ...
    def limits(self) -> dict: ...
