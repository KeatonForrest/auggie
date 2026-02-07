"""
test_api_usability.py - Tests for API usability fixes

Tests for standardized errors, /v1/account endpoint, webhook retries,
job timeouts, and query param validation.
"""

import asyncio
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch, MagicMock

from fastapi import HTTPException

from api.errors import APIError
from api.routes import SortField, SortOrder


# ============================================================================
# APIError tests
# ============================================================================


class TestAPIError:
    """Tests for the APIError exception class."""

    def test_api_error_is_http_exception(self):
        """APIError is a subclass of HTTPException."""
        err = APIError("not_found", "Job not found", 404)
        assert isinstance(err, HTTPException)

    def test_api_error_has_structured_detail(self):
        """APIError.detail is a dict with code and message."""
        err = APIError("insufficient_credits", "No credits remaining", 402)
        assert err.detail == {"code": "insufficient_credits", "message": "No credits remaining"}

    def test_api_error_status_code(self):
        """APIError preserves the status code."""
        err = APIError("internal_error", "Something broke", 500)
        assert err.status_code == 500

    def test_api_error_default_status_code(self):
        """APIError defaults to 400 if no status_code given."""
        err = APIError("validation_error", "Bad input")
        assert err.status_code == 400

    def test_api_error_attributes(self):
        """APIError has error_code and error_message attributes."""
        err = APIError("rate_limit_exceeded", "Slow down", 429)
        assert err.error_code == "rate_limit_exceeded"
        assert err.error_message == "Slow down"


# ============================================================================
# /v1/account endpoint tests
# ============================================================================


class TestAccountEndpoint:
    """Tests for the GET /v1/account endpoint."""

    @pytest.mark.asyncio
    async def test_account_returns_expected_shape(self):
        """GET /v1/account returns user, org, credits, subscription, api_keys."""
        from api.routes import get_account

        fake_api_user = {"id": 1, "api_key_id": 42}
        fake_user = {
            "id": 1,
            "email": "test@co.com",
            "org_name": "Acme Corp",
            "org_slug": "acme-corp",
        }
        fake_usage = {
            "bonus_credits": 84700,
            "subscription_status": "active",
            "billing_period_start": datetime(2025, 1, 1, tzinfo=timezone.utc),
            "is_admin": False,
        }
        fake_keys = [
            {
                "id": 1,
                "prefix": "sk_live_abc1",
                "name": "Default",
                "created_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
                "last_used_at": datetime(2025, 6, 1, tzinfo=timezone.utc),
            }
        ]
        fake_stats = {1: {"requests": 142, "credits": 130}}

        with patch("api.routes.default_limiter") as mock_limiter, \
             patch("api.routes.get_user_usage", new_callable=AsyncMock, return_value=fake_usage), \
             patch("database.get_user_by_id", new_callable=AsyncMock, return_value=fake_user), \
             patch("db.api_keys.list_api_keys", new_callable=AsyncMock, return_value=fake_keys), \
             patch("db.api_keys.get_api_key_usage_stats", new_callable=AsyncMock, return_value=fake_stats):

            result = await get_account(api_user=fake_api_user)

        assert result["user_id"] == 1
        assert result["email"] == "test@co.com"
        assert result["organization"]["name"] == "Acme Corp"
        assert result["organization"]["slug"] == "acme-corp"
        assert result["credits"]["balance"] == 847
        assert result["credits"]["unit"] == "credits"
        assert result["subscription"]["status"] == "active"
        assert len(result["api_keys"]) == 1
        assert result["api_keys"][0]["prefix"] == "sk_live_abc1"
        assert result["api_keys"][0]["usage"] == {"requests": 142, "credits": 130}

    @pytest.mark.asyncio
    async def test_account_user_not_found(self):
        """GET /v1/account raises 404 if user doesn't exist."""
        from api.routes import get_account

        with patch("api.routes.default_limiter"), \
             patch("database.get_user_by_id", new_callable=AsyncMock, return_value=None):

            with pytest.raises(APIError) as exc_info:
                await get_account(api_user={"id": 999, "api_key_id": 1})

            assert exc_info.value.status_code == 404


# ============================================================================
# Webhook retry tests
# ============================================================================


class TestWebhookRetries:
    """Tests for webhook delivery with exponential backoff."""

    @pytest.mark.asyncio
    async def test_webhook_success_on_first_attempt(self):
        """Webhook delivered successfully on first try."""
        from api.jobs import _deliver_webhook

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("api.jobs.get_user_webhook", new_callable=AsyncMock, return_value={"id": 1, "url": "https://example.com/hook", "secret": "s3cret"}), \
             patch("api.jobs.create_webhook_delivery", new_callable=AsyncMock, return_value={"id": 10}), \
             patch("api.jobs.sign_payload", return_value="abc123"), \
             patch("api.jobs.update_delivery_status", new_callable=AsyncMock) as mock_update, \
             patch("api.jobs.httpx.AsyncClient") as mock_client_cls:

            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            await _deliver_webhook(1, 100, "completed", 50, None)

            mock_update.assert_called_once_with(10, status="success", http_status=200, attempts=1)

    @pytest.mark.asyncio
    async def test_webhook_retries_on_500_then_succeeds(self):
        """Webhook retries on 500 and eventually succeeds."""
        from api.jobs import _deliver_webhook

        mock_resp_500 = MagicMock()
        mock_resp_500.status_code = 500
        mock_resp_200 = MagicMock()
        mock_resp_200.status_code = 200

        with patch("api.jobs.get_user_webhook", new_callable=AsyncMock, return_value={"id": 1, "url": "https://example.com/hook", "secret": "s3cret"}), \
             patch("api.jobs.create_webhook_delivery", new_callable=AsyncMock, return_value={"id": 10}), \
             patch("api.jobs.sign_payload", return_value="abc123"), \
             patch("api.jobs.update_delivery_status", new_callable=AsyncMock) as mock_update, \
             patch("api.jobs.httpx.AsyncClient") as mock_client_cls, \
             patch("api.jobs.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:

            mock_client = AsyncMock()
            mock_client.post.side_effect = [mock_resp_500, mock_resp_200]
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            await _deliver_webhook(1, 100, "completed", 50, None)

            # Should have retried once
            mock_sleep.assert_called_once()
            # Final call is success on attempt 2
            mock_update.assert_called_with(10, status="success", http_status=200, attempts=2)

    @pytest.mark.asyncio
    async def test_webhook_no_retry_on_4xx(self):
        """Webhook does NOT retry on 4xx client errors."""
        from api.jobs import _deliver_webhook

        mock_resp = MagicMock()
        mock_resp.status_code = 404

        with patch("api.jobs.get_user_webhook", new_callable=AsyncMock, return_value={"id": 1, "url": "https://example.com/hook", "secret": "s3cret"}), \
             patch("api.jobs.create_webhook_delivery", new_callable=AsyncMock, return_value={"id": 10}), \
             patch("api.jobs.sign_payload", return_value="abc123"), \
             patch("api.jobs.update_delivery_status", new_callable=AsyncMock) as mock_update, \
             patch("api.jobs.httpx.AsyncClient") as mock_client_cls, \
             patch("api.jobs.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:

            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            await _deliver_webhook(1, 100, "completed", 50, None)

            # No retry sleep
            mock_sleep.assert_not_called()
            # Marked failed immediately
            mock_update.assert_called_once_with(10, status="failed", http_status=404, attempts=1)

    @pytest.mark.asyncio
    async def test_webhook_no_delivery_without_webhook(self):
        """No webhook configured — returns immediately."""
        from api.jobs import _deliver_webhook

        with patch("api.jobs.get_user_webhook", new_callable=AsyncMock, return_value=None) as mock_get, \
             patch("api.jobs.create_webhook_delivery", new_callable=AsyncMock) as mock_create:

            await _deliver_webhook(1, 100, "completed", 50, None)

            mock_create.assert_not_called()

    @pytest.mark.asyncio
    async def test_webhook_retries_on_429(self):
        """Webhook retries on 429 Too Many Requests."""
        from api.jobs import _deliver_webhook

        mock_resp_429 = MagicMock()
        mock_resp_429.status_code = 429
        mock_resp_200 = MagicMock()
        mock_resp_200.status_code = 200

        with patch("api.jobs.get_user_webhook", new_callable=AsyncMock, return_value={"id": 1, "url": "https://example.com/hook", "secret": "s3cret"}), \
             patch("api.jobs.create_webhook_delivery", new_callable=AsyncMock, return_value={"id": 10}), \
             patch("api.jobs.sign_payload", return_value="abc123"), \
             patch("api.jobs.update_delivery_status", new_callable=AsyncMock) as mock_update, \
             patch("api.jobs.httpx.AsyncClient") as mock_client_cls, \
             patch("api.jobs.asyncio.sleep", new_callable=AsyncMock):

            mock_client = AsyncMock()
            mock_client.post.side_effect = [mock_resp_429, mock_resp_200]
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            await _deliver_webhook(1, 100, "completed", 50, None)

            mock_update.assert_called_with(10, status="success", http_status=200, attempts=2)


# ============================================================================
# Job timeout tests
# ============================================================================


class TestJobTimeout:
    """Tests for read-path job timeouts."""

    @pytest.mark.asyncio
    async def test_processing_job_times_out_after_10_minutes(self):
        """Job in processing >10 min is marked failed on poll."""
        from api.routes import get_job_status

        old_time = datetime.now(timezone.utc) - timedelta(minutes=15)
        fake_processing_job = {
            "id": 42,
            "status": "processing",
            "progress": "scraping",
            "company_url": "https://acme.com",
            "created_at": old_time,
            "completed_at": None,
            "document_id": None,
            "error_message": None,
        }
        fake_failed_job = {
            **fake_processing_job,
            "status": "failed",
            "error_message": "Job timed out after 10 minutes",
        }

        call_count = 0
        async def mock_get_job(job_id, user_id):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return fake_processing_job
            return fake_failed_job

        with patch("api.routes.default_limiter"), \
             patch("api.routes.get_research_job", new_callable=AsyncMock, side_effect=mock_get_job), \
             patch("api.routes.get_user_usage", new_callable=AsyncMock, return_value={"is_admin": False}), \
             patch("api.routes.refund_credit", new_callable=AsyncMock) as mock_refund, \
             patch("database.update_job_status", new_callable=AsyncMock) as mock_update:

            result = await get_job_status(42, api_user={"id": 1, "api_key_id": 1})

            mock_update.assert_called_once_with(42, "failed", error_message="Job timed out after 10 minutes")
            mock_refund.assert_called_once_with(1)
            assert result["status"] == "failed"
            assert result["error"] == "Job timed out after 10 minutes"

    @pytest.mark.asyncio
    async def test_processing_job_under_10_minutes_not_timed_out(self):
        """Job in processing <10 min is NOT timed out."""
        from api.routes import get_job_status

        recent_time = datetime.now(timezone.utc) - timedelta(minutes=5)
        fake_job = {
            "id": 42,
            "status": "processing",
            "progress": "analyzing",
            "company_url": "https://acme.com",
            "created_at": recent_time,
            "completed_at": None,
            "document_id": None,
            "error_message": None,
        }

        with patch("api.routes.default_limiter"), \
             patch("api.routes.get_research_job", new_callable=AsyncMock, return_value=fake_job), \
             patch("database.update_job_status", new_callable=AsyncMock) as mock_update:

            result = await get_job_status(42, api_user={"id": 1, "api_key_id": 1})

            mock_update.assert_not_called()
            assert result["status"] == "processing"


# ============================================================================
# Query param validation tests
# ============================================================================


class TestQueryParamValidation:
    """Tests for query param enum and constraint validation."""

    def test_sort_field_enum_values(self):
        """SortField has expected values."""
        assert SortField.composite_score == "composite_score"
        assert SortField.pain_score == "pain_score"
        assert SortField.fit_score == "fit_score"
        assert SortField.timing_score == "timing_score"
        assert SortField.created_at == "created_at"

    def test_sort_order_enum_values(self):
        """SortOrder has expected values."""
        assert SortOrder.asc == "asc"
        assert SortOrder.desc == "desc"

    def test_invalid_sort_field_rejected(self):
        """Invalid sort field value raises ValueError."""
        with pytest.raises(ValueError):
            SortField("invalid_field")

    def test_invalid_sort_order_rejected(self):
        """Invalid sort order value raises ValueError."""
        with pytest.raises(ValueError):
            SortOrder("random")

    def test_sort_field_value_property(self):
        """SortField.value returns the string value."""
        assert SortField.pain_score.value == "pain_score"

    def test_sort_order_value_property(self):
        """SortOrder.value returns the string value."""
        assert SortOrder.desc.value == "desc"


# ============================================================================
# Error response format tests
# ============================================================================


class TestErrorResponseFormat:
    """Tests for the standardized error response format in exception handlers."""

    def test_api_error_detail_is_structured_dict(self):
        """APIError.detail is the structured format used by the exception handler."""
        err = APIError("unauthorized", "Invalid API key", 401)
        # The handler checks isinstance(exc.detail, dict) and "code" in exc.detail
        assert isinstance(err.detail, dict)
        assert "code" in err.detail
        assert "message" in err.detail
        assert err.detail == {"code": "unauthorized", "message": "Invalid API key"}

    def test_error_response_format_matches_spec(self):
        """The error response wrapping matches {"error": {"code": ..., "message": ...}}."""
        # Simulate what the exception handler does
        err = APIError("insufficient_credits", "No credits remaining. Need 5, have 2.", 402)
        # Handler produces: {"error": exc.detail}
        response_body = {"error": err.detail}
        assert response_body == {
            "error": {
                "code": "insufficient_credits",
                "message": "No credits remaining. Need 5, have 2.",
            }
        }


# ============================================================================
# Rate limiter enforce mode tests
# ============================================================================


class TestRateLimiterEnforceMode:
    """Tests for InMemoryRateLimiter enforce vs warn-only mode."""

    def test_enforce_true_raises_429(self):
        """enforce=True raises HTTPException(429) when limit exceeded."""
        from api.ratelimit import InMemoryRateLimiter

        limiter = InMemoryRateLimiter(requests=2, window_seconds=60, enforce=True)
        limiter.check("key1")
        limiter.check("key1")

        with pytest.raises(HTTPException) as exc_info:
            limiter.check("key1")
        assert exc_info.value.status_code == 429

    def test_enforce_false_warns_but_does_not_raise(self):
        """enforce=False logs a warning but does NOT raise 429."""
        from api.ratelimit import InMemoryRateLimiter

        limiter = InMemoryRateLimiter(requests=2, window_seconds=60, enforce=False)
        limiter.check("key1")
        limiter.check("key1")

        # Should not raise — warn-only mode
        limiter.check("key1")
        limiter.check("key1")

    def test_enforce_false_still_tracks_hits(self):
        """enforce=False still records hits for observability."""
        from api.ratelimit import InMemoryRateLimiter

        limiter = InMemoryRateLimiter(requests=1, window_seconds=60, enforce=False)
        limiter.check("key1")
        limiter.check("key1")
        limiter.check("key1")

        # Hits are tracked even beyond the limit
        assert len(limiter._hits["key1"]) >= 3

    def test_enforce_default_is_true(self):
        """enforce defaults to True when not specified."""
        from api.ratelimit import InMemoryRateLimiter

        limiter = InMemoryRateLimiter(requests=1, window_seconds=60)
        assert limiter.enforce is True


# ============================================================================
# Clay endpoint timeout tests
# ============================================================================


class TestClayTimeout:
    """Tests for the 120s timeout on POST /v1/clay/enrich."""

    @pytest.mark.asyncio
    async def test_clay_enrich_timeout_returns_504(self):
        """Pipeline exceeding timeout returns 504 with timeout error."""
        from api.routes import clay_enrich

        body = MagicMock()
        body.company_url = "https://example.com"

        fake_api_user = {"id": 1, "api_key_id": 42}
        fake_usage = {"is_admin": False}
        fake_job = {"id": 100}

        async def hang_forever(user_id, url):
            await asyncio.Event().wait()

        with patch("api.routes.clay_limiter"), \
             patch("api.routes.CLAY_TIMEOUT", 0.1), \
             patch("api.routes.validate_company_url", return_value="https://example.com"), \
             patch("api.routes.get_recent_document_by_url", new_callable=AsyncMock, return_value=None), \
             patch("api.routes.get_user_usage", new_callable=AsyncMock, return_value=fake_usage), \
             patch("api.routes.create_job_with_credit", new_callable=AsyncMock, return_value=fake_job), \
             patch("api.routes._run_research_pipeline", side_effect=hang_forever), \
             patch("api.routes.refund_credit", new_callable=AsyncMock) as mock_refund, \
             patch("database.update_job_status", new_callable=AsyncMock) as mock_update:

            with pytest.raises(APIError) as exc_info:
                await clay_enrich(body, api_user=fake_api_user)

            assert exc_info.value.status_code == 504
            assert exc_info.value.error_code == "timeout"
            mock_refund.assert_called_once_with(1)
            mock_update.assert_called_once_with(100, "failed", error_message="Research timed out after 120 seconds")

    @pytest.mark.asyncio
    async def test_clay_enrich_timeout_no_refund_for_admin(self):
        """Admin users don't get refunded on timeout."""
        from api.routes import clay_enrich

        body = MagicMock()
        body.company_url = "https://example.com"

        fake_api_user = {"id": 1, "api_key_id": 42}
        fake_usage = {"is_admin": True}
        fake_job = {"id": 100}

        async def hang_forever(user_id, url):
            await asyncio.Event().wait()

        with patch("api.routes.clay_limiter"), \
             patch("api.routes.CLAY_TIMEOUT", 0.1), \
             patch("api.routes.validate_company_url", return_value="https://example.com"), \
             patch("api.routes.get_recent_document_by_url", new_callable=AsyncMock, return_value=None), \
             patch("api.routes.get_user_usage", new_callable=AsyncMock, return_value=fake_usage), \
             patch("api.routes.create_research_job", new_callable=AsyncMock, return_value=fake_job), \
             patch("api.routes._run_research_pipeline", side_effect=hang_forever), \
             patch("api.routes.refund_credit", new_callable=AsyncMock) as mock_refund, \
             patch("database.update_job_status", new_callable=AsyncMock):

            with pytest.raises(APIError) as exc_info:
                await clay_enrich(body, api_user=fake_api_user)

            assert exc_info.value.status_code == 504
            mock_refund.assert_not_called()
