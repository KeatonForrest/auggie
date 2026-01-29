"""In-memory sliding window rate limiter for API endpoints."""

import time
from collections import defaultdict
from fastapi import HTTPException


class RateLimiter:
    """Sliding window rate limiter keyed by API key ID.

    In-memory only — resets on deploy, which is fine for v1.
    """

    def __init__(self, requests: int, window_seconds: int):
        self.requests = requests
        self.window = window_seconds
        self._hits: dict[int, list[float]] = defaultdict(list)

    def check(self, api_key_id: int) -> None:
        """Raise 429 if rate limit exceeded."""
        now = time.monotonic()
        cutoff = now - self.window

        hits = [t for t in self._hits[api_key_id] if t > cutoff]

        if len(hits) >= self.requests:
            retry_after = int(hits[0] - cutoff) + 1
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded. Max {self.requests} requests per {self.window}s.",
                headers={"Retry-After": str(retry_after)},
            )

        hits.append(now)
        self._hits[api_key_id] = hits

    def _cleanup(self) -> None:
        """Remove keys with no recent hits. Call periodically if needed."""
        now = time.monotonic()
        cutoff = now - self.window
        empty = [k for k, v in self._hits.items() if not any(t > cutoff for t in v)]
        for k in empty:
            del self._hits[k]


# Shared limiters (API key-based)
research_limiter = RateLimiter(requests=10, window_seconds=60)
sequence_limiter = RateLimiter(requests=20, window_seconds=60)
default_limiter = RateLimiter(requests=60, window_seconds=60)
bulk_limiter = RateLimiter(requests=2, window_seconds=60)
clay_limiter = RateLimiter(requests=5, window_seconds=60)


class IPRateLimiter:
    """Sliding window rate limiter keyed by client IP address."""

    def __init__(self, requests: int, window_seconds: int):
        self.requests = requests
        self.window = window_seconds
        self._hits: dict[str, list[float]] = defaultdict(list)

    def check(self, ip: str) -> None:
        """Raise 429 if rate limit exceeded."""
        now = time.monotonic()
        cutoff = now - self.window

        hits = [t for t in self._hits[ip] if t > cutoff]

        if len(hits) >= self.requests:
            retry_after = int(hits[0] - cutoff) + 1
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded. Max {self.requests} requests per {self.window}s.",
                headers={"Retry-After": str(retry_after)},
            )

        hits.append(now)
        self._hits[ip] = hits

    def _cleanup(self) -> None:
        """Remove keys with no recent hits. Call periodically if needed."""
        now = time.monotonic()
        cutoff = now - self.window
        empty = [k for k, v in self._hits.items() if not any(t > cutoff for t in v)]
        for k in empty:
            del self._hits[k]


def get_client_ip(request) -> str:
    """Extract client IP, checking X-Forwarded-For for reverse proxy setups."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# Shared IP-based limiters (web form endpoints)
auth_limiter = IPRateLimiter(requests=10, window_seconds=60)
research_web_limiter = IPRateLimiter(requests=5, window_seconds=60)
upload_limiter = IPRateLimiter(requests=3, window_seconds=60)
