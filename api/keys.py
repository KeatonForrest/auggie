"""API key generation and hashing."""

import secrets
import bcrypt


def generate_api_key() -> tuple[str, str, str]:
    """Generate a new API key.

    Returns (raw_key, key_hash, prefix) where:
    - raw_key: the full key shown to user once (sk_live_...)
    - key_hash: bcrypt hash stored in DB
    - prefix: first 8 chars after sk_live_ for identification
    """
    random_part = secrets.token_urlsafe(32)
    raw_key = f"sk_live_{random_part}"
    prefix = raw_key[:16]  # "sk_live_" + first 8 chars
    key_hash = bcrypt.hashpw(raw_key.encode(), bcrypt.gensalt()).decode()
    return raw_key, key_hash, prefix


def verify_api_key(raw_key: str, key_hash: str) -> bool:
    """Check a raw API key against a stored bcrypt hash."""
    return bcrypt.checkpw(raw_key.encode(), key_hash.encode())
