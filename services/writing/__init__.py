"""services.writing - AI-powered outreach generation package.

Re-exports for backward compatibility.
"""

from services.writing.service import WritingService, SequenceValidationError
from services.writing.types import LINKEDIN_WORD_LIMITS

__all__ = ["WritingService", "SequenceValidationError", "LINKEDIN_WORD_LIMITS"]
