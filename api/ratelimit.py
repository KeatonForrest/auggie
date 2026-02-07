"""In-memory sliding window rate limiter for API endpoints.

Includes periodic cleanup and max-key eviction to prevent unbounded memory growth.
Interface is kept abstract so a Redis backend can be swapped in later.
"""

import abc
import logging
import threading
import time
from collections import defaultdict
from fastapi import HTTPException

logger = logging.getLogger(__name__)

MAX_KEYS = 10_000
CLEANUP_INTERVAL = 60  # seconds

# Registry of all limiter instances for the cleanup thread
_all_limiters: list["InMemoryRateLimiter"] = []
_cleanup_lock = threading.Lock()
_cleanup_started = False


def _start_cleanup_thread() -> None:
    """Start a single daemon thread that periodically cleans all limiters."""
    global _cleanup_started
    with _cleanup_lock:
        if _cleanup_started:
            return
        _cleanup_started = True

    def _run() -> None:
        while True:
            time.sleep(CLEANUP_INTERVAL)
            for limiter in _all_limiters:
                try:
                    limiter._cleanup()
                except Exception:
                    pass

    t = threading.Thread(target=_run, daemon=True)
    t.start()


class BaseRateLimiter(abc.ABC):
    """Abstract rate limiter interface — swap in Redis by subclassing."""

    @abc.abstractmethod
    def check(self, key) -> None:
        """Raise HTTPException(429) if rate limit exceeded."""


class InMemoryRateLimiter(BaseRateLimiter):
    """Sliding window rate limiter with cleanup and max-key eviction."""

    def __init__(self, requests: int, window_seconds: int, enforce: bool = True):
        self.requests = requests
        self.window = window_seconds
        self.enforce = enforce
        self._hits: dict = defaultdict(list)
        self._lock = threading.Lock()
        _all_limiters.append(self)
        _start_cleanup_thread()

    def check(self, key) -> None:
        """Raise 429 if rate limit exceeded."""
        now = time.monotonic()
        cutoff = now - self.window

        with self._lock:
            hits = [t for t in self._hits[key] if t > cutoff]

            if len(hits) >= self.requests:
                if not self.enforce:
                    logger.warning(
                        "Rate limit exceeded (warn-only): key=%s, limit=%d/%ds",
                        key, self.requests, self.window,
                    )
                else:
                    retry_after = int(hits[0] - cutoff) + 1
                    raise HTTPException(
                        status_code=429,
                        detail=f"Rate limit exceeded. Max {self.requests} requests per {self.window}s.",
                        headers={"Retry-After": str(retry_after)},
                    )

            hits.append(now)
            self._hits[key] = hits

            # Evict oldest keys if we exceed MAX_KEYS
            if len(self._hits) > MAX_KEYS:
                self._evict_oldest()

    def _evict_oldest(self) -> None:
        """Remove the oldest-accessed keys to bring count under MAX_KEYS."""
        # Sort keys by their most recent hit timestamp
        by_latest = sorted(self._hits.items(), key=lambda kv: max(kv[1]) if kv[1] else 0)
        to_remove = len(self._hits) - MAX_KEYS
        for k, _ in by_latest[:to_remove]:
            del self._hits[k]

    def _cleanup(self) -> None:
        """Remove keys with no recent hits."""
        now = time.monotonic()
        cutoff = now - self.window
        with self._lock:
            empty = [k for k, v in self._hits.items() if not any(t > cutoff for t in v)]
            for k in empty:
                del self._hits[k]


# Backwards-compatible aliases
RateLimiter = InMemoryRateLimiter
IPRateLimiter = InMemoryRateLimiter

# Load config to determine enforcement mode for API-key-based limiters
from config import get_settings
_settings = get_settings()
_api_enforce = not _settings.cloudflare_rate_limiting

# Shared limiters (API key-based) — warn-only when Cloudflare rate limiting is active
research_limiter = RateLimiter(requests=10, window_seconds=60, enforce=_api_enforce)
sequence_limiter = RateLimiter(requests=20, window_seconds=60, enforce=_api_enforce)
default_limiter = RateLimiter(requests=60, window_seconds=60, enforce=_api_enforce)
bulk_limiter = RateLimiter(requests=2, window_seconds=60, enforce=_api_enforce)
clay_limiter = RateLimiter(requests=5, window_seconds=60, enforce=_api_enforce)


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
