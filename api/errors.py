"""Standardized API error handling.

Provides APIError exception class and consistent error response format:
    {"error": {"code": "...", "message": "..."}}
"""

from fastapi import HTTPException
from pydantic import BaseModel, Field


class APIError(HTTPException):
    """Structured API error with machine-readable code.

    Usage:
        raise APIError("insufficient_credits", "No credits remaining. Need 5, have 2.", 402)
        raise APIError("rate_limit_exceeded", "Too fast", 429, headers={"Retry-After": "5"})
    """

    def __init__(self, code: str, message: str, status_code: int = 400, headers: dict[str, str] | None = None):
        self.error_code = code
        self.error_message = message
        super().__init__(status_code=status_code, detail={"code": code, "message": message}, headers=headers)


# =============================================================================
# OpenAPI error documentation models
# =============================================================================

class ErrorDetail(BaseModel):
    code: str = Field(..., description="Machine-readable error code", examples=["not_found"])
    message: str = Field(..., description="Human-readable error message", examples=["Resource not found"])
    request_id: str | None = Field(None, description="Request ID for support reference", examples=["req_abc123"])

class ErrorResponse(BaseModel):
    error: ErrorDetail


def _error_responses(*codes: int) -> dict:
    """Build FastAPI ``responses`` dict for given HTTP status codes."""
    _ERRORS: dict[int, dict] = {
        401: {
            "model": ErrorResponse,
            "description": "Invalid or missing API key",
            "content": {"application/json": {"example": {"error": {"code": "unauthorized", "message": "Invalid or revoked API key", "request_id": "req_abc123"}}}},
        },
        402: {
            "model": ErrorResponse,
            "description": "Insufficient credits",
            "content": {"application/json": {"example": {"error": {"code": "insufficient_credits", "message": "No credits remaining", "request_id": "req_abc123"}}}},
        },
        403: {
            "model": ErrorResponse,
            "description": "Forbidden",
            "content": {"application/json": {"example": {"error": {"code": "forbidden", "message": "Admin access required", "request_id": "req_abc123"}}}},
        },
        404: {
            "model": ErrorResponse,
            "description": "Resource not found",
            "content": {"application/json": {"example": {"error": {"code": "not_found", "message": "Resource not found", "request_id": "req_abc123"}}}},
        },
        409: {
            "model": ErrorResponse,
            "description": "Conflict",
            "content": {"application/json": {"example": {"error": {"code": "conflict", "message": "Resource is already being processed", "request_id": "req_abc123"}}}},
        },
        422: {
            "model": ErrorResponse,
            "description": "Validation error",
            "content": {"application/json": {"example": {"error": {"code": "validation_error", "message": "Invalid input", "request_id": "req_abc123"}}}},
        },
        429: {
            "model": ErrorResponse,
            "description": "Rate limit exceeded",
            "content": {"application/json": {"example": {"error": {"code": "rate_limit_exceeded", "message": "Rate limit exceeded. Retry after 60 seconds", "request_id": "req_abc123"}}}},
        },
    }
    return {code: _ERRORS[code] for code in codes if code in _ERRORS}
