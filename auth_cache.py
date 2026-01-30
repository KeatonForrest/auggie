"""auth_cache.py - TTL cache for authenticated user lookups."""

from cachetools import TTLCache

# 256 users, 30s TTL
_user_cache: TTLCache = TTLCache(maxsize=256, ttl=30)


def get_cached_user(user_id: int) -> dict | None:
    """Return cached user dict or None."""
    return _user_cache.get(user_id)


def set_cached_user(user_id: int, user: dict) -> None:
    """Store a user dict in the cache."""
    _user_cache[user_id] = user


def invalidate_user_cache(user_id: int) -> None:
    """Remove a user from the cache so the next request fetches fresh data."""
    _user_cache.pop(user_id, None)
