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


# Shared limiters
research_limiter = RateLimiter(requests=10, window_seconds=60)
sequence_limiter = RateLimiter(requests=20, window_seconds=60)
default_limiter = RateLimiter(requests=60, window_seconds=60)
bulk_limiter = RateLimiter(requests=2, window_seconds=60)
clay_limiter = RateLimiter(requests=5, window_seconds=60)
