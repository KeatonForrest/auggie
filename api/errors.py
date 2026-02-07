"""Standardized API error handling.

Provides APIError exception class and consistent error response format:
    {"error": {"code": "...", "message": "..."}}
"""

from fastapi import HTTPException


class APIError(HTTPException):
    """Structured API error with machine-readable code.

    Usage:
        raise APIError("insufficient_credits", "No credits remaining. Need 5, have 2.", 402)
    """

    def __init__(self, code: str, message: str, status_code: int = 400):
        self.error_code = code
        self.error_message = message
        super().__init__(status_code=status_code, detail={"code": code, "message": message})
