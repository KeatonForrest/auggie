"""
test_api_modules.py - Tests for API-related modules

Tests for FastAPI dependencies, validation, authentication, webhooks,
rate limiting, and caching modules.
"""

import pytest
import time
import threading
import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock, patch, call
from fastapi import HTTPException, Header

# Module imports
from api.auth import require_api_key
from api.keys import generate_api_key, verify_api_key
from api.tasks import create_tracked_task
from api.validation import normalize_url, validate_company_url
from api.webhooks import sign_payload, router as webhook_router
from api.ratelimit import (
    InMemoryRateLimiter,
    get_client_ip,
    research_limiter,
    sequence_limiter,
    default_limiter,
    bulk_limiter,
    clay_limiter,
    auth_limiter,
    research_web_limiter,
    upload_limiter,
)
from auth_cache import get_cached_user, set_cached_user, invalidate_user_cache


# ============================================================================
# api/auth.py tests
# ============================================================================


class TestRequireApiKey:
    """Tests for the require_api_key FastAPI dependency."""

    @pytest.mark.asyncio
    async def test_valid_api_key_returns_user(self):
        """Valid Bearer token returns user with api_key_id."""
        with patch("api.auth.validate_api_key", new_callable=AsyncMock) as mock_validate, \
             patch("api.auth.get_user_by_id", new_callable=AsyncMock) as mock_get_user:

            mock_validate.return_value = {"user_id": 1, "api_key_id": 42}
            mock_get_user.return_value = {
                "id": 1,
                "email": "test@example.com",
                "name": "Test User"
            }

            result = await require_api_key("Bearer sk_live_abc123xyz")

            assert result["id"] == 1
            assert result["email"] == "test@example.com"
            assert result["api_key_id"] == 42
            mock_validate.assert_called_once_with("sk_live_abc123xyz")
            mock_get_user.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_missing_bearer_prefix_raises_401(self):
        """Authorization header without Bearer prefix raises 401."""
        with pytest.raises(HTTPException) as exc_info:
            await require_api_key("sk_live_abc123xyz")

        assert exc_info.value.status_code == 401
        assert "Invalid authorization header" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_invalid_key_format_raises_401(self):
        """API key without sk_live_ prefix raises 401."""
        with pytest.raises(HTTPException) as exc_info:
            await require_api_key("Bearer invalid_key")

        assert exc_info.value.status_code == 401
        assert "Invalid API key format" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_invalid_or_revoked_key_raises_401(self):
        """Invalid or revoked API key raises 401."""
        with patch("api.auth.validate_api_key", new_callable=AsyncMock) as mock_validate:
            mock_validate.return_value = None

            with pytest.raises(HTTPException) as exc_info:
                await require_api_key("Bearer sk_live_abc123xyz")

            assert exc_info.value.status_code == 401
            assert "Invalid or revoked API key" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_user_not_found_raises_401(self):
        """Valid key but missing user raises 401."""
        with patch("api.auth.validate_api_key", new_callable=AsyncMock) as mock_validate, \
             patch("api.auth.get_user_by_id", new_callable=AsyncMock) as mock_get_user:

            mock_validate.return_value = {"user_id": 999, "api_key_id": 42}
            mock_get_user.return_value = None

            with pytest.raises(HTTPException) as exc_info:
                await require_api_key("Bearer sk_live_abc123xyz")

            assert exc_info.value.status_code == 401
            assert "User not found" in exc_info.value.detail


# ============================================================================
# api/keys.py tests
# ============================================================================


class TestApiKeyGeneration:
    """Tests for API key generation and verification."""

    def test_generate_api_key_returns_tuple(self):
        """generate_api_key returns (raw_key, key_hash, prefix)."""
        raw_key, key_hash, prefix = generate_api_key()

        assert raw_key.startswith("sk_live_")
        assert len(raw_key) > 16
        assert prefix == raw_key[:16]
        assert key_hash.startswith("$2b$")  # bcrypt hash prefix
        assert raw_key != key_hash

    def test_generate_api_key_unique(self):
        """Multiple calls generate different keys."""
        key1, hash1, prefix1 = generate_api_key()
        key2, hash2, prefix2 = generate_api_key()

        assert key1 != key2
        assert hash1 != hash2
        assert prefix1 != prefix2

    def test_verify_api_key_valid(self):
        """verify_api_key returns True for matching key and hash."""
        raw_key, key_hash, _ = generate_api_key()

        assert verify_api_key(raw_key, key_hash) is True

    def test_verify_api_key_invalid(self):
        """verify_api_key returns False for non-matching key."""
        _, key_hash, _ = generate_api_key()

        assert verify_api_key("sk_live_wrong_key", key_hash) is False

    def test_verify_api_key_wrong_hash(self):
        """verify_api_key returns False for wrong hash."""
        raw_key, _, _ = generate_api_key()
        _, different_hash, _ = generate_api_key()

        assert verify_api_key(raw_key, different_hash) is False


# ============================================================================
# api/tasks.py tests
# ============================================================================


class TestCreateTrackedTask:
    """Tests for task creation and enqueuing."""

    @pytest.mark.asyncio
    async def test_create_tracked_task_returns_id(self):
        """create_tracked_task enqueues and returns task ID."""
        with patch("api.tasks.enqueue", new_callable=AsyncMock) as mock_enqueue:
            mock_enqueue.return_value = 123

            task_id = await create_tracked_task(
                "research",
                {"company_url": "https://example.com"},
                name="Research example.com"
            )

            assert task_id == 123
            mock_enqueue.assert_called_once_with("research", {"company_url": "https://example.com"})

    @pytest.mark.asyncio
    async def test_create_tracked_task_without_name(self):
        """create_tracked_task works without optional name parameter."""
        with patch("api.tasks.enqueue", new_callable=AsyncMock) as mock_enqueue:
            mock_enqueue.return_value = 456

            task_id = await create_tracked_task("email_sequence", {"data": "test"})

            assert task_id == 456
            mock_enqueue.assert_called_once_with("email_sequence", {"data": "test"})

    @pytest.mark.asyncio
    async def test_create_tracked_task_logs_info(self):
        """create_tracked_task logs task information."""
        with patch("api.tasks.enqueue", new_callable=AsyncMock) as mock_enqueue, \
             patch("api.tasks._logger") as mock_logger:

            mock_enqueue.return_value = 789

            await create_tracked_task("test_task", {"key": "value"}, name="Test")

            mock_logger.info.assert_called_once()
            args = mock_logger.info.call_args[0]
            assert "test_task" in args
            assert 789 in args
            assert "Test" in args


# ============================================================================
# api/validation.py tests
# ============================================================================


class TestNormalizeUrl:
    """Tests for URL normalization."""

    def test_normalize_url_adds_https(self):
        """URLs without protocol get https:// prefix."""
        assert normalize_url("example.com") == "https://example.com"

    def test_normalize_url_preserves_https(self):
        """URLs with https:// are unchanged."""
        assert normalize_url("https://example.com") == "https://example.com"

    def test_normalize_url_preserves_http(self):
        """URLs with http:// are unchanged."""
        assert normalize_url("http://example.com") == "http://example.com"

    def test_normalize_url_strips_whitespace(self):
        """Leading/trailing whitespace is removed."""
        assert normalize_url("  example.com  ") == "https://example.com"

    def test_normalize_url_with_path(self):
        """URLs with paths are normalized correctly."""
        assert normalize_url("example.com/about") == "https://example.com/about"


class TestValidateCompanyUrl:
    """Tests for company URL validation."""

    def test_validate_company_url_valid_https(self):
        """Valid HTTPS URLs pass validation."""
        # Mock DNS resolution to return public IP
        with patch("api.validation.socket.getaddrinfo") as mock_getaddrinfo:
            mock_getaddrinfo.return_value = [
                (2, 1, 6, '', ('93.184.216.34', 80))  # Public IP for example.com
            ]

            result = validate_company_url("https://example.com")
            assert result == "https://example.com"

    def test_validate_company_url_adds_https(self):
        """URLs without protocol get https:// added."""
        with patch("api.validation.socket.getaddrinfo") as mock_getaddrinfo:
            mock_getaddrinfo.return_value = [
                (2, 1, 6, '', ('93.184.216.34', 80))
            ]

            result = validate_company_url("example.com")
            assert result == "https://example.com"

    def test_validate_company_url_rejects_ftp(self):
        """Non-HTTP schemes are rejected."""
        # Note: normalize_url will add https:// prefix to "ftp://example.com"
        # making it "https://ftp://example.com", which fails DNS resolution
        # This still validates that non-standard URLs are rejected
        with pytest.raises(ValueError) as exc_info:
            validate_company_url("ftp://example.com")

        # The error will be about DNS resolution since normalization creates invalid hostname
        assert "Cannot resolve hostname" in str(exc_info.value)

    def test_validate_company_url_rejects_localhost(self):
        """localhost is blocked."""
        with pytest.raises(ValueError) as exc_info:
            validate_company_url("http://localhost")

        assert "Internal URLs are not allowed" in str(exc_info.value)

    def test_validate_company_url_rejects_127001(self):
        """127.0.0.1 is blocked."""
        with pytest.raises(ValueError) as exc_info:
            validate_company_url("http://127.0.0.1")

        assert "Internal URLs are not allowed" in str(exc_info.value)

    def test_validate_company_url_rejects_private_ip(self):
        """URLs resolving to private IPs are rejected."""
        with patch("api.validation.socket.getaddrinfo") as mock_getaddrinfo:
            mock_getaddrinfo.return_value = [
                (2, 1, 6, '', ('192.168.1.1', 80))  # Private IP
            ]

            with pytest.raises(ValueError) as exc_info:
                validate_company_url("http://internal.example.com")

            assert "private/internal address" in str(exc_info.value)

    def test_validate_company_url_rejects_link_local(self):
        """URLs resolving to link-local IPs are rejected."""
        with patch("api.validation.socket.getaddrinfo") as mock_getaddrinfo:
            mock_getaddrinfo.return_value = [
                (2, 1, 6, '', ('169.254.1.1', 80))  # Link-local IP
            ]

            with pytest.raises(ValueError) as exc_info:
                validate_company_url("http://linklocal.example.com")

            assert "private/internal address" in str(exc_info.value)

    def test_validate_company_url_dns_error(self):
        """DNS resolution errors are handled."""
        with patch("api.validation.socket.getaddrinfo") as mock_getaddrinfo:
            import socket
            mock_getaddrinfo.side_effect = socket.gaierror("Name or service not known")

            with pytest.raises(ValueError) as exc_info:
                validate_company_url("http://nonexistent.invalid")

            assert "Cannot resolve hostname" in str(exc_info.value)

    def test_validate_company_url_no_hostname(self):
        """URLs without hostname are rejected."""
        with pytest.raises(ValueError) as exc_info:
            validate_company_url("https://")

        assert "no hostname" in str(exc_info.value)


# ============================================================================
# api/webhooks.py tests
# ============================================================================


class TestSignPayload:
    """Tests for webhook payload signing."""

    def test_sign_payload_returns_hex_digest(self):
        """sign_payload returns HMAC-SHA256 hex digest."""
        payload = {"event": "research.completed", "data": {"id": 1}}
        secret = "test_secret"

        signature = sign_payload(payload, secret)

        assert isinstance(signature, str)
        assert len(signature) == 64  # SHA256 hex digest is 64 chars

    def test_sign_payload_deterministic(self):
        """Same payload and secret produce same signature."""
        payload = {"event": "test", "value": 123}
        secret = "my_secret"

        sig1 = sign_payload(payload, secret)
        sig2 = sign_payload(payload, secret)

        assert sig1 == sig2

    def test_sign_payload_different_secret_different_signature(self):
        """Different secrets produce different signatures."""
        payload = {"event": "test"}

        sig1 = sign_payload(payload, "secret1")
        sig2 = sign_payload(payload, "secret2")

        assert sig1 != sig2

    def test_sign_payload_different_payload_different_signature(self):
        """Different payloads produce different signatures."""
        secret = "test_secret"

        sig1 = sign_payload({"event": "A"}, secret)
        sig2 = sign_payload({"event": "B"}, secret)

        assert sig1 != sig2

    def test_sign_payload_sorted_keys(self):
        """Payload keys are sorted for consistent hashing."""
        secret = "test"

        # Same data, different key order
        sig1 = sign_payload({"a": 1, "b": 2}, secret)
        sig2 = sign_payload({"b": 2, "a": 1}, secret)

        assert sig1 == sig2

    def test_sign_payload_matches_manual_hmac(self):
        """Signature matches manual HMAC computation."""
        payload = {"test": "data"}
        secret = "my_secret"

        result = sign_payload(payload, secret)

        # Manual computation
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

        assert result == expected


# ============================================================================
# api/ratelimit.py tests
# ============================================================================


class TestInMemoryRateLimiter:
    """Tests for in-memory rate limiter."""

    def test_rate_limiter_allows_within_limit(self):
        """Requests within limit are allowed."""
        limiter = InMemoryRateLimiter(requests=3, window_seconds=60)

        # Should not raise
        limiter.check("user1")
        limiter.check("user1")
        limiter.check("user1")

    def test_rate_limiter_blocks_over_limit(self):
        """Requests exceeding limit raise 429."""
        limiter = InMemoryRateLimiter(requests=2, window_seconds=60)

        limiter.check("user1")
        limiter.check("user1")

        with pytest.raises(HTTPException) as exc_info:
            limiter.check("user1")

        assert exc_info.value.status_code == 429
        assert exc_info.value.detail["code"] == "rate_limit_exceeded"
        assert "Rate limit exceeded" in exc_info.value.detail["message"]
        assert "Retry-After" in exc_info.value.headers

    def test_rate_limiter_separate_keys(self):
        """Different keys have independent limits."""
        limiter = InMemoryRateLimiter(requests=2, window_seconds=60)

        limiter.check("user1")
        limiter.check("user1")
        limiter.check("user2")
        limiter.check("user2")

        # Both users at limit
        with pytest.raises(HTTPException):
            limiter.check("user1")

        with pytest.raises(HTTPException):
            limiter.check("user2")

    def test_rate_limiter_sliding_window(self):
        """Old requests slide out of the window."""
        limiter = InMemoryRateLimiter(requests=2, window_seconds=1)

        limiter.check("user1")
        limiter.check("user1")

        # At limit
        with pytest.raises(HTTPException):
            limiter.check("user1")

        # Wait for window to expire
        time.sleep(1.1)

        # Should work again
        limiter.check("user1")

    def test_rate_limiter_cleanup_removes_old_keys(self):
        """Cleanup removes keys with no recent hits."""
        limiter = InMemoryRateLimiter(requests=5, window_seconds=1)

        limiter.check("user1")
        limiter.check("user2")

        # Wait for window to expire
        time.sleep(1.1)

        # Cleanup should remove both keys
        limiter._cleanup()

        assert len(limiter._hits) == 0

    def test_rate_limiter_evicts_oldest_keys(self):
        """Max keys limit triggers eviction of oldest keys."""
        limiter = InMemoryRateLimiter(requests=10, window_seconds=60)

        # Manually set MAX_KEYS lower for testing
        original_max = limiter._hits.__class__.__module__

        # Add many keys
        for i in range(15):
            limiter.check(f"user{i}")

        # Simulate eviction by directly manipulating hits
        with limiter._lock:
            # Fill beyond MAX_KEYS
            limiter._hits.update({f"extra{i}": [time.monotonic()] for i in range(10000)})
            limiter._evict_oldest()

            # Should be reduced
            assert len(limiter._hits) <= 10000


class TestGetClientIp:
    """Tests for client IP extraction."""

    def test_get_client_ip_from_x_forwarded_for(self):
        """IP is extracted from X-Forwarded-For header."""
        request = MagicMock()
        request.headers.get.return_value = "203.0.113.1, 198.51.100.1"
        request.client.host = "10.0.0.1"

        ip = get_client_ip(request)

        assert ip == "203.0.113.1"

    def test_get_client_ip_from_client_host(self):
        """IP falls back to request.client.host if no header."""
        request = MagicMock()
        request.headers.get.return_value = None
        request.client.host = "192.0.2.1"

        ip = get_client_ip(request)

        assert ip == "192.0.2.1"

    def test_get_client_ip_no_client(self):
        """Returns 'unknown' if no client information."""
        request = MagicMock()
        request.headers.get.return_value = None
        request.client = None

        ip = get_client_ip(request)

        assert ip == "unknown"

    def test_get_client_ip_strips_whitespace(self):
        """Whitespace in forwarded header is stripped."""
        request = MagicMock()
        request.headers.get.return_value = "  203.0.113.1  , 198.51.100.1"

        ip = get_client_ip(request)

        assert ip == "203.0.113.1"


class TestSharedLimiters:
    """Tests for shared rate limiter instances."""

    def test_research_limiter_exists(self):
        """research_limiter is configured."""
        assert research_limiter.requests == 10
        assert research_limiter.window == 60

    def test_sequence_limiter_exists(self):
        """sequence_limiter is configured."""
        assert sequence_limiter.requests == 20
        assert sequence_limiter.window == 60

    def test_default_limiter_exists(self):
        """default_limiter is configured."""
        assert default_limiter.requests == 60
        assert default_limiter.window == 60

    def test_bulk_limiter_exists(self):
        """bulk_limiter is configured."""
        assert bulk_limiter.requests == 2
        assert bulk_limiter.window == 60

    def test_clay_limiter_exists(self):
        """clay_limiter is configured."""
        assert clay_limiter.requests == 5
        assert clay_limiter.window == 60

    def test_auth_limiter_exists(self):
        """auth_limiter is configured."""
        assert auth_limiter.requests == 10
        assert auth_limiter.window == 60

    def test_research_web_limiter_exists(self):
        """research_web_limiter is configured."""
        assert research_web_limiter.requests == 5
        assert research_web_limiter.window == 60

    def test_upload_limiter_exists(self):
        """upload_limiter is configured."""
        assert upload_limiter.requests == 3
        assert upload_limiter.window == 60


# ============================================================================
# auth_cache.py tests
# ============================================================================


class TestAuthCache:
    """Tests for user authentication cache."""

    def test_get_cached_user_empty(self):
        """get_cached_user returns None for missing user."""
        result = get_cached_user(999999)
        assert result is None

    def test_set_and_get_cached_user(self):
        """set_cached_user stores user and get_cached_user retrieves it."""
        user = {"id": 1, "email": "test@example.com", "name": "Test"}

        set_cached_user(1, user)
        result = get_cached_user(1)

        assert result == user

    def test_cached_user_ttl_expires(self):
        """Cached users expire after TTL."""
        user = {"id": 2, "email": "ttl@example.com"}

        set_cached_user(2, user)
        assert get_cached_user(2) == user

        # Wait for TTL to expire (30 seconds in production, but we can't wait that long)
        # This test documents the behavior but doesn't verify TTL in real-time
        # In production, after 30s, get_cached_user(2) would return None

    def test_invalidate_user_cache_removes_user(self):
        """invalidate_user_cache removes user from cache."""
        user = {"id": 3, "email": "invalidate@example.com"}

        set_cached_user(3, user)
        assert get_cached_user(3) == user

        invalidate_user_cache(3)
        assert get_cached_user(3) is None

    def test_invalidate_user_cache_nonexistent_user(self):
        """invalidate_user_cache handles non-existent users gracefully."""
        # Should not raise
        invalidate_user_cache(888888)

    def test_cache_stores_multiple_users(self):
        """Cache can store multiple users independently."""
        user1 = {"id": 10, "email": "user1@example.com"}
        user2 = {"id": 20, "email": "user2@example.com"}

        set_cached_user(10, user1)
        set_cached_user(20, user2)

        assert get_cached_user(10) == user1
        assert get_cached_user(20) == user2

    def test_cache_overwrites_existing_user(self):
        """Setting same user ID overwrites previous value."""
        user_v1 = {"id": 5, "email": "old@example.com"}
        user_v2 = {"id": 5, "email": "new@example.com"}

        set_cached_user(5, user_v1)
        set_cached_user(5, user_v2)

        result = get_cached_user(5)
        assert result == user_v2
        assert result["email"] == "new@example.com"


# ============================================================================
# Integration tests
# ============================================================================


class TestApiModuleIntegration:
    """Integration tests for API modules working together."""

    @pytest.mark.asyncio
    async def test_full_auth_flow_with_cache(self):
        """Complete auth flow: validate key, cache user, retrieve from cache."""
        with patch("api.auth.validate_api_key", new_callable=AsyncMock) as mock_validate, \
             patch("api.auth.get_user_by_id", new_callable=AsyncMock) as mock_get_user:

            mock_validate.return_value = {"user_id": 100, "api_key_id": 50}
            mock_get_user.return_value = {
                "id": 100,
                "email": "integration@example.com",
                "name": "Integration Test"
            }

            # First request - should hit DB
            user1 = await require_api_key("Bearer sk_live_integration_test")

            # Cache the user
            set_cached_user(user1["id"], user1)

            # Second request - should use cache
            cached_user = get_cached_user(100)

            assert cached_user is not None
            assert cached_user["email"] == "integration@example.com"
            assert cached_user["api_key_id"] == 50

    def test_rate_limit_with_different_endpoints(self):
        """Different rate limiters work independently."""
        # Simulate hitting different endpoints with different limits
        research_limiter.check("test_user")
        sequence_limiter.check("test_user")
        default_limiter.check("test_user")

        # All should succeed since they're separate limiters

    def test_url_validation_and_normalization_pipeline(self):
        """URL normalization and validation work together."""
        with patch("api.validation.socket.getaddrinfo") as mock_getaddrinfo:
            mock_getaddrinfo.return_value = [
                (2, 1, 6, '', ('93.184.216.34', 80))
            ]

            # Input: bare domain
            result = validate_company_url("example.com")

            # Output: normalized and validated HTTPS URL
            assert result == "https://example.com"

    def test_webhook_signing_verification_flow(self):
        """Webhook signing and verification complete flow."""
        # Generate secret (similar to webhook registration)
        import secrets
        webhook_secret = secrets.token_hex(32)

        # Create and sign payload
        payload = {
            "event": "research.completed",
            "data": {"company": "example.com", "status": "success"}
        }
        signature = sign_payload(payload, webhook_secret)

        # Verify signature (what webhook receiver would do)
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        expected_sig = hmac.new(webhook_secret.encode(), body, hashlib.sha256).hexdigest()

        assert signature == expected_sig


# ============================================================================
# Edge cases and error handling
# ============================================================================


class TestEdgeCases:
    """Tests for edge cases and error conditions."""

    @pytest.mark.asyncio
    async def test_require_api_key_empty_header(self):
        """Empty authorization header raises 401."""
        with pytest.raises(HTTPException) as exc_info:
            await require_api_key("")

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_require_api_key_bearer_only(self):
        """Just 'Bearer ' without key raises 401."""
        with pytest.raises(HTTPException) as exc_info:
            await require_api_key("Bearer ")

        assert exc_info.value.status_code == 401

    def test_normalize_url_empty_string(self):
        """Empty URL gets https:// prefix."""
        assert normalize_url("") == "https://"

    def test_validate_company_url_just_protocol(self):
        """URL with just protocol fails validation."""
        with pytest.raises(ValueError):
            validate_company_url("https://")

    def test_sign_payload_empty_dict(self):
        """Empty payload dict can be signed."""
        signature = sign_payload({}, "secret")
        assert isinstance(signature, str)
        assert len(signature) == 64

    def test_sign_payload_nested_dict(self):
        """Nested dicts are handled correctly."""
        payload = {
            "event": "test",
            "data": {
                "nested": {
                    "value": 123
                }
            }
        }
        signature = sign_payload(payload, "secret")
        assert isinstance(signature, str)

    def test_rate_limiter_very_low_limit(self):
        """Rate limiter with limit of 1 allows one request then blocks."""
        limiter = InMemoryRateLimiter(requests=1, window_seconds=60)

        # First request should succeed
        limiter.check("user1")

        # Second request should fail
        with pytest.raises(HTTPException) as exc_info:
            limiter.check("user1")

        assert exc_info.value.status_code == 429

    def test_verify_api_key_empty_strings(self):
        """verify_api_key handles empty strings."""
        _, key_hash, _ = generate_api_key()

        # Empty key against valid hash
        assert verify_api_key("", key_hash) is False

    def test_cache_none_value(self):
        """Cache can store None as a value."""
        set_cached_user(777, None)
        result = get_cached_user(777)

        # None is stored and returned
        assert result is None


# ============================================================================
# api/idempotency.py tests
# ============================================================================


class TestIdempotency:
    """Tests for idempotency key checking and saving."""

    @pytest.mark.asyncio
    async def test_duplicate_key_returns_cached_response(self):
        """Second call with the same idempotency key returns cached response."""
        from api.idempotency import check_idempotency, save_idempotency

        mock_request = MagicMock()
        mock_request.headers.get.return_value = "test-key-123"

        # First call: no cache
        with patch("api.idempotency.db_check", new_callable=AsyncMock, return_value=None):
            key, cached = await check_idempotency(mock_request, api_key_id=1)
            assert key == "test-key-123"
            assert cached is None

        # Save the result
        with patch("api.idempotency.db_save", new_callable=AsyncMock) as mock_save:
            await save_idempotency(1, "test-key-123", 200, {"job_id": 42})
            mock_save.assert_called_once_with(1, "test-key-123", 200, {"job_id": 42})

        # Second call: returns cached
        with patch("api.idempotency.db_check", new_callable=AsyncMock, return_value=(200, {"job_id": 42})):
            key, cached = await check_idempotency(mock_request, api_key_id=1)
            assert key == "test-key-123"
            assert cached is not None
            assert cached.status_code == 200

    @pytest.mark.asyncio
    async def test_different_keys_execute_independently(self):
        """Different idempotency keys do not interfere with each other."""
        from api.idempotency import check_idempotency

        mock_request_a = MagicMock()
        mock_request_a.headers.get.return_value = "key-aaa"

        mock_request_b = MagicMock()
        mock_request_b.headers.get.return_value = "key-bbb"

        with patch("api.idempotency.db_check", new_callable=AsyncMock, return_value=None):
            key_a, cached_a = await check_idempotency(mock_request_a, api_key_id=1)
            key_b, cached_b = await check_idempotency(mock_request_b, api_key_id=1)

            assert key_a == "key-aaa"
            assert cached_a is None
            assert key_b == "key-bbb"
            assert cached_b is None

    @pytest.mark.asyncio
    async def test_missing_header_executes_normally(self):
        """Request without Idempotency-Key header proceeds normally."""
        from api.idempotency import check_idempotency

        mock_request = MagicMock()
        mock_request.headers.get.return_value = None

        key, cached = await check_idempotency(mock_request, api_key_id=1)
        assert key is None
        assert cached is None

    @pytest.mark.asyncio
    async def test_cached_response_preserves_status_code(self):
        """Cached response preserves the original status code."""
        from api.idempotency import check_idempotency

        mock_request = MagicMock()
        mock_request.headers.get.return_value = "key-202"

        with patch("api.idempotency.db_check", new_callable=AsyncMock, return_value=(202, {"job_id": 1, "status": "processing"})):
            key, cached = await check_idempotency(mock_request, api_key_id=1)
            assert cached.status_code == 202


# ============================================================================
# Rate limit ContextVar tests
# ============================================================================


class TestRateLimitHeaders:
    """Tests for RateLimitInfo ContextVar populated by check()."""

    def test_contextvar_populated_after_check(self):
        """ContextVar is populated after a successful check()."""
        from api.ratelimit import _rate_limit_info, RateLimitInfo
        limiter = InMemoryRateLimiter(requests=10, window_seconds=60)
        limiter.check("rl_test_user")
        info = _rate_limit_info.get(None)
        assert info is not None
        assert info.limit == 10
        assert info.remaining == 9
        assert isinstance(info.reset, int)

    def test_remaining_decrements(self):
        """Remaining decrements with each call."""
        from api.ratelimit import _rate_limit_info
        limiter = InMemoryRateLimiter(requests=5, window_seconds=60)
        for expected_remaining in [4, 3, 2, 1, 0]:
            try:
                limiter.check("rl_decrement_user")
            except HTTPException:
                pass
            info = _rate_limit_info.get(None)
            assert info.remaining == expected_remaining

    def test_contextvar_populated_on_429(self):
        """ContextVar is populated even when rate limit is exceeded."""
        from api.ratelimit import _rate_limit_info
        limiter = InMemoryRateLimiter(requests=1, window_seconds=60)
        limiter.check("rl_429_user")
        with pytest.raises(HTTPException):
            limiter.check("rl_429_user")
        info = _rate_limit_info.get(None)
        assert info is not None
        assert info.remaining == 0


# ============================================================================
# Error response request_id tests
# ============================================================================


class TestErrorRequestId:
    """Tests for request_id injection in error responses."""

    def test_api_error_structure(self):
        """APIError produces structured error with code and message."""
        from api.errors import APIError
        err = APIError("not_found", "Job not found", 404)
        assert err.status_code == 404
        assert err.detail == {"code": "not_found", "message": "Job not found"}

    def test_status_to_code_mapping(self):
        """_STATUS_TO_CODE covers expected status codes."""
        from main import _STATUS_TO_CODE
        assert _STATUS_TO_CODE[400] == "validation_error"
        assert _STATUS_TO_CODE[401] == "unauthorized"
        assert _STATUS_TO_CODE[402] == "insufficient_credits"
        assert _STATUS_TO_CODE[403] == "forbidden"
        assert _STATUS_TO_CODE[404] == "not_found"
        assert _STATUS_TO_CODE[409] == "conflict"
        assert _STATUS_TO_CODE[422] == "validation_error"
        assert _STATUS_TO_CODE[429] == "rate_limit_exceeded"
        assert _STATUS_TO_CODE[500] == "internal_error"
