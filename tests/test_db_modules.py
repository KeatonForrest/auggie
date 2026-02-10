"""Tests for database modules in db/."""

import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models import ResearchDocument


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_pool():
    """Create a mock pool with async context manager support."""
    mock_conn = AsyncMock()
    mock_pool = MagicMock()  # Pool is NOT async, acquire() is sync method returning async context manager

    # Set up the acquire() context manager
    mock_acquire = AsyncMock()
    mock_acquire.__aenter__.return_value = mock_conn
    mock_acquire.__aexit__.return_value = None
    mock_pool.acquire.return_value = mock_acquire

    return mock_pool, mock_conn


# ============================================================================
# db/api_keys.py tests
# ============================================================================

class TestApiKeys:
    """Tests for db/api_keys.py"""

    @pytest.mark.asyncio
    async def test_create_api_key_record(self, mock_pool):
        """Test creating an API key record."""
        from db import api_keys

        mock_pool_obj, mock_conn = mock_pool
        mock_conn.fetchrow.return_value = {"id": 123}

        with patch("db._pool._pool", mock_pool_obj):
            result = await api_keys.create_api_key_record(
                user_id=1,
                key_hash="hash123",
                prefix="prefix123",
                name="Test Key"
            )

        assert result == 123
        mock_conn.fetchrow.assert_called_once()
        call_args = mock_conn.fetchrow.call_args[0]
        assert "INSERT INTO api_keys" in call_args[0]
        assert call_args[1:] == (1, "hash123", "prefix123", "Test Key")

    @pytest.mark.asyncio
    async def test_validate_api_key_success(self, mock_pool):
        """Test validating a valid API key."""
        from db import api_keys

        mock_pool_obj, mock_conn = mock_pool
        mock_conn.fetch.return_value = [
            {"id": 1, "user_id": 10, "key_hash": "stored_hash"}
        ]

        # Mock the verify function that's imported inside validate_api_key
        mock_verify = MagicMock(return_value=True)

        with patch("db._pool._pool", mock_pool_obj), \
             patch("api.keys.verify_api_key", mock_verify):
            result = await api_keys.validate_api_key("prefix123_rawkey")

        assert result == {"user_id": 10, "api_key_id": 1}
        mock_conn.execute.assert_called_once()
        assert "UPDATE api_keys SET last_used_at" in mock_conn.execute.call_args[0][0]

    @pytest.mark.asyncio
    async def test_validate_api_key_invalid(self, mock_pool):
        """Test validating an invalid API key."""
        from db import api_keys

        mock_pool_obj, mock_conn = mock_pool
        mock_conn.fetch.return_value = [
            {"id": 1, "user_id": 10, "key_hash": "stored_hash"}
        ]

        # Mock the verify function that's imported inside validate_api_key
        mock_verify = MagicMock(return_value=False)

        with patch("db._pool._pool", mock_pool_obj), \
             patch("api.keys.verify_api_key", mock_verify):
            result = await api_keys.validate_api_key("prefix123_wrongkey")

        assert result is None

    @pytest.mark.asyncio
    async def test_validate_api_key_no_matching_prefix(self, mock_pool):
        """Test validating when no keys match the prefix."""
        from db import api_keys

        mock_pool_obj, mock_conn = mock_pool
        mock_conn.fetch.return_value = []

        # Mock the verify function (won't be called but need to avoid import error)
        mock_verify = MagicMock()

        with patch("db._pool._pool", mock_pool_obj), \
             patch("api.keys.verify_api_key", mock_verify):
            result = await api_keys.validate_api_key("wrongprefix_rawkey")

        assert result is None

    @pytest.mark.asyncio
    async def test_list_api_keys(self, mock_pool):
        """Test listing API keys for a user."""
        from db import api_keys

        mock_pool_obj, mock_conn = mock_pool
        mock_conn.fetch.return_value = [
            {"id": 1, "prefix": "pre1", "name": "Key 1", "created_at": "2024-01-01", "last_used_at": None},
            {"id": 2, "prefix": "pre2", "name": "Key 2", "created_at": "2024-01-02", "last_used_at": "2024-01-03"},
        ]

        with patch("db._pool._pool", mock_pool_obj):
            result = await api_keys.list_api_keys(user_id=1)

        assert len(result) == 2
        assert result[0]["id"] == 1
        assert result[1]["id"] == 2
        mock_conn.fetch.assert_called_once()
        call_args = mock_conn.fetch.call_args[0]
        assert "SELECT id, prefix, name, created_at, last_used_at" in call_args[0]
        assert call_args[1] == 1

    @pytest.mark.asyncio
    async def test_list_api_keys_empty(self, mock_pool):
        """Test listing when user has no API keys."""
        from db import api_keys

        mock_pool_obj, mock_conn = mock_pool
        mock_conn.fetch.return_value = []

        with patch("db._pool._pool", mock_pool_obj):
            result = await api_keys.list_api_keys(user_id=1)

        assert result == []

    @pytest.mark.asyncio
    async def test_revoke_api_key_success(self, mock_pool):
        """Test revoking an API key."""
        from db import api_keys

        mock_pool_obj, mock_conn = mock_pool
        mock_conn.execute.return_value = "UPDATE 1"

        with patch("db._pool._pool", mock_pool_obj):
            result = await api_keys.revoke_api_key(key_id=1, user_id=10)

        assert result is True
        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args[0]
        assert "UPDATE api_keys SET revoked = TRUE" in call_args[0]
        assert call_args[1:] == (1, 10)

    @pytest.mark.asyncio
    async def test_revoke_api_key_not_found(self, mock_pool):
        """Test revoking a non-existent or already revoked key."""
        from db import api_keys

        mock_pool_obj, mock_conn = mock_pool
        mock_conn.execute.return_value = "UPDATE 0"

        with patch("db._pool._pool", mock_pool_obj):
            result = await api_keys.revoke_api_key(key_id=999, user_id=10)

        assert result is False

    @pytest.mark.asyncio
    async def test_record_api_usage(self, mock_pool):
        """Test recording API usage."""
        from db import api_keys

        mock_pool_obj, mock_conn = mock_pool

        with patch("db._pool._pool", mock_pool_obj):
            await api_keys.record_api_usage(api_key_id=1, endpoint="/research", credits_used=5)

        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args[0]
        assert "INSERT INTO api_usage" in call_args[0]
        assert call_args[1:] == (1, "/research", 5)

    @pytest.mark.asyncio
    async def test_get_api_key_usage_stats(self, mock_pool):
        """Test getting usage stats for user's API keys."""
        from db import api_keys

        mock_pool_obj, mock_conn = mock_pool
        mock_conn.fetch.return_value = [
            {"key_id": 1, "request_count": 10, "credits_used": 50},
            {"key_id": 2, "request_count": 5, "credits_used": 25},
        ]

        with patch("db._pool._pool", mock_pool_obj):
            result = await api_keys.get_api_key_usage_stats(user_id=1)

        assert result == {
            1: {"requests": 10, "credits": 50},
            2: {"requests": 5, "credits": 25},
        }
        mock_conn.fetch.assert_called_once()
        call_args = mock_conn.fetch.call_args[0]
        assert "SELECT ak.id AS key_id" in call_args[0]
        assert call_args[1] == 1


# ============================================================================
# db/integrations.py tests
# ============================================================================

class TestIntegrations:
    """Tests for db/integrations.py"""

    @pytest.mark.asyncio
    async def test_upsert_integration_insert(self, mock_pool):
        """Test inserting a new integration."""
        from db import integrations

        mock_pool_obj, mock_conn = mock_pool
        mock_conn.fetchrow.return_value = {
            "id": 1,
            "user_id": 10,
            "provider": "google",
            "access_token": "token123",
            "refresh_token": "refresh123",
            "token_expires_at": None,
            "metadata": {"key": "value"},
        }

        with patch("db._pool._pool", mock_pool_obj):
            result = await integrations.upsert_integration(
                user_id=10,
                provider="google",
                access_token="token123",
                refresh_token="refresh123",
                metadata={"key": "value"}
            )

        assert result["id"] == 1
        assert result["provider"] == "google"
        mock_conn.fetchrow.assert_called_once()
        call_args = mock_conn.fetchrow.call_args[0]
        assert "INSERT INTO integrations" in call_args[0]
        assert "ON CONFLICT (user_id, provider)" in call_args[0]

    @pytest.mark.asyncio
    async def test_upsert_integration_update(self, mock_pool):
        """Test updating an existing integration."""
        from db import integrations

        mock_pool_obj, mock_conn = mock_pool
        mock_conn.fetchrow.return_value = {
            "id": 1,
            "user_id": 10,
            "provider": "google",
            "access_token": "new_token",
            "refresh_token": "refresh123",
            "token_expires_at": None,
            "metadata": {},
        }

        with patch("db._pool._pool", mock_pool_obj):
            result = await integrations.upsert_integration(
                user_id=10,
                provider="google",
                access_token="new_token",
            )

        assert result["access_token"] == "new_token"

    @pytest.mark.asyncio
    async def test_get_integration_exists(self, mock_pool):
        """Test getting an existing integration."""
        from db import integrations

        mock_pool_obj, mock_conn = mock_pool
        mock_conn.fetchrow.return_value = {
            "id": 1,
            "user_id": 10,
            "provider": "google",
            "access_token": "token123",
        }

        with patch("db._pool._pool", mock_pool_obj):
            result = await integrations.get_integration(user_id=10, provider="google")

        assert result is not None
        assert result["provider"] == "google"
        mock_conn.fetchrow.assert_called_once()
        call_args = mock_conn.fetchrow.call_args[0]
        assert "SELECT * FROM integrations WHERE user_id = $1 AND provider = $2" in call_args[0]
        assert call_args[1:] == (10, "google")

    @pytest.mark.asyncio
    async def test_get_integration_not_exists(self, mock_pool):
        """Test getting a non-existent integration."""
        from db import integrations

        mock_pool_obj, mock_conn = mock_pool
        mock_conn.fetchrow.return_value = None

        with patch("db._pool._pool", mock_pool_obj):
            result = await integrations.get_integration(user_id=10, provider="unknown")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_user_integrations(self, mock_pool):
        """Test getting all integrations for a user."""
        from db import integrations

        mock_pool_obj, mock_conn = mock_pool
        mock_conn.fetch.return_value = [
            {"id": 1, "user_id": 10, "provider": "google"},
            {"id": 2, "user_id": 10, "provider": "salesforce"},
        ]

        with patch("db._pool._pool", mock_pool_obj):
            result = await integrations.get_user_integrations(user_id=10)

        assert len(result) == 2
        assert result[0]["provider"] == "google"
        assert result[1]["provider"] == "salesforce"
        mock_conn.fetch.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_user_integrations_empty(self, mock_pool):
        """Test getting integrations when user has none."""
        from db import integrations

        mock_pool_obj, mock_conn = mock_pool
        mock_conn.fetch.return_value = []

        with patch("db._pool._pool", mock_pool_obj):
            result = await integrations.get_user_integrations(user_id=10)

        assert result == []

    @pytest.mark.asyncio
    async def test_delete_integration_success(self, mock_pool):
        """Test deleting an integration."""
        from db import integrations

        mock_pool_obj, mock_conn = mock_pool
        mock_conn.execute.return_value = "DELETE 1"

        with patch("db._pool._pool", mock_pool_obj):
            result = await integrations.delete_integration(user_id=10, provider="google")

        assert result is True
        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args[0]
        assert "DELETE FROM integrations" in call_args[0]
        assert call_args[1:] == (10, "google")

    @pytest.mark.asyncio
    async def test_delete_integration_not_found(self, mock_pool):
        """Test deleting a non-existent integration."""
        from db import integrations

        mock_pool_obj, mock_conn = mock_pool
        mock_conn.execute.return_value = "DELETE 0"

        with patch("db._pool._pool", mock_pool_obj):
            result = await integrations.delete_integration(user_id=10, provider="unknown")

        assert result is False

    @pytest.mark.asyncio
    async def test_update_integration_tokens(self, mock_pool):
        """Test updating integration tokens."""
        from db import integrations

        mock_pool_obj, mock_conn = mock_pool
        expires_at = datetime(2024, 12, 31)

        with patch("db._pool._pool", mock_pool_obj):
            await integrations.update_integration_tokens(
                user_id=10,
                provider="google",
                access_token="new_access",
                refresh_token="new_refresh",
                token_expires_at=expires_at
            )

        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args[0]
        assert "UPDATE integrations SET" in call_args[0]
        assert call_args[1:] == (10, "google", "new_access", "new_refresh", expires_at)


# ============================================================================
# db/feedback.py tests
# ============================================================================

class TestFeedback:
    """Tests for db/feedback.py"""

    @pytest.mark.asyncio
    async def test_save_feedback(self, mock_pool):
        """Test saving feedback."""
        from db import feedback

        mock_pool_obj, mock_conn = mock_pool

        with patch("db._pool._pool", mock_pool_obj):
            await feedback.save_feedback(
                document_id=1,
                user_id=10,
                is_positive=True,
                comment="Great research!"
            )

        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args[0]
        assert "INSERT INTO research_feedback" in call_args[0]
        assert "ON CONFLICT (document_id, user_id)" in call_args[0]
        assert call_args[1:] == (1, 10, True, "Great research!")

    @pytest.mark.asyncio
    async def test_save_feedback_no_comment(self, mock_pool):
        """Test saving feedback without a comment."""
        from db import feedback

        mock_pool_obj, mock_conn = mock_pool

        with patch("db._pool._pool", mock_pool_obj):
            await feedback.save_feedback(
                document_id=1,
                user_id=10,
                is_positive=False
            )

        call_args = mock_conn.execute.call_args[0]
        assert call_args[1:] == (1, 10, False, None)

    @pytest.mark.asyncio
    async def test_get_feedback_exists(self, mock_pool):
        """Test getting existing feedback."""
        from db import feedback

        mock_pool_obj, mock_conn = mock_pool
        mock_conn.fetchrow.return_value = {
            "is_positive": True,
            "comment": "Great!"
        }

        with patch("db._pool._pool", mock_pool_obj):
            result = await feedback.get_feedback(document_id=1, user_id=10)

        assert result == {"is_positive": True, "comment": "Great!"}
        mock_conn.fetchrow.assert_called_once()
        call_args = mock_conn.fetchrow.call_args[0]
        assert "SELECT is_positive, comment FROM research_feedback" in call_args[0]
        assert call_args[1:] == (1, 10)

    @pytest.mark.asyncio
    async def test_get_feedback_not_exists(self, mock_pool):
        """Test getting non-existent feedback."""
        from db import feedback

        mock_pool_obj, mock_conn = mock_pool
        mock_conn.fetchrow.return_value = None

        with patch("db._pool._pool", mock_pool_obj):
            result = await feedback.get_feedback(document_id=1, user_id=10)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_all_feedback(self, mock_pool):
        """Test getting all feedback."""
        from db import feedback

        mock_pool_obj, mock_conn = mock_pool
        mock_conn.fetch.return_value = [
            {
                "id": 1,
                "document_id": 10,
                "user_id": 1,
                "is_positive": True,
                "comment": "Good",
                "created_at": "2024-01-01",
                "model_used": "claude-3",
                "opportunity_score": 8,
                "pain_score": 7,
                "fit_score": 9,
                "timing_score": 6,
                "company_name": "Acme Corp",
            }
        ]

        with patch("db._pool._pool", mock_pool_obj):
            result = await feedback.get_all_feedback(limit=100)

        assert len(result) == 1
        assert result[0]["is_positive"] is True
        assert result[0]["company_name"] == "Acme Corp"
        mock_conn.fetch.assert_called_once()
        call_args = mock_conn.fetch.call_args[0]
        assert "JOIN research_documents d ON d.id = f.document_id" in call_args[0]
        assert call_args[1] == 100

    @pytest.mark.asyncio
    async def test_get_all_feedback_custom_limit(self, mock_pool):
        """Test getting all feedback with custom limit."""
        from db import feedback

        mock_pool_obj, mock_conn = mock_pool
        mock_conn.fetch.return_value = []

        with patch("db._pool._pool", mock_pool_obj):
            await feedback.get_all_feedback(limit=50)

        call_args = mock_conn.fetch.call_args[0]
        assert call_args[1] == 50


# ============================================================================
# db/webhooks.py tests
# ============================================================================

class TestWebhooks:
    """Tests for db/webhooks.py"""

    @pytest.mark.asyncio
    async def test_upsert_webhook(self, mock_pool):
        """Test upserting a webhook."""
        from db import webhooks

        mock_pool_obj, mock_conn = mock_pool
        mock_conn.fetchval.return_value = 5  # org_id
        mock_conn.fetchrow.return_value = {
            "id": 1,
            "user_id": 10,
            "url": "https://example.com/hook",
            "secret": "secret123",
            "active": True,
            "org_id": 5,
        }

        with patch("db._pool._pool", mock_pool_obj):
            result = await webhooks.upsert_webhook(
                user_id=10,
                url="https://example.com/hook",
                secret="secret123"
            )

        assert result["url"] == "https://example.com/hook"
        assert result["active"] is True
        mock_conn.fetchval.assert_called_once()
        mock_conn.fetchrow.assert_called_once()
        call_args = mock_conn.fetchrow.call_args[0]
        assert "INSERT INTO webhooks" in call_args[0]
        assert "ON CONFLICT (user_id)" in call_args[0]

    @pytest.mark.asyncio
    async def test_get_user_webhook_exists(self, mock_pool):
        """Test getting an existing webhook."""
        from db import webhooks

        mock_pool_obj, mock_conn = mock_pool
        mock_conn.fetchrow.return_value = {
            "id": 1,
            "user_id": 10,
            "url": "https://example.com/hook",
            "secret": "secret123",
            "active": True,
        }

        with patch("db._pool._pool", mock_pool_obj):
            result = await webhooks.get_user_webhook(user_id=10)

        assert result is not None
        assert result["url"] == "https://example.com/hook"
        mock_conn.fetchrow.assert_called_once()
        call_args = mock_conn.fetchrow.call_args[0]
        assert "SELECT * FROM webhooks WHERE user_id = $1 AND active = TRUE" in call_args[0]

    @pytest.mark.asyncio
    async def test_get_user_webhook_not_exists(self, mock_pool):
        """Test getting when no webhook exists."""
        from db import webhooks

        mock_pool_obj, mock_conn = mock_pool
        mock_conn.fetchrow.return_value = None

        with patch("db._pool._pool", mock_pool_obj):
            result = await webhooks.get_user_webhook(user_id=10)

        assert result is None

    @pytest.mark.asyncio
    async def test_delete_user_webhook_success(self, mock_pool):
        """Test deleting a webhook."""
        from db import webhooks

        mock_pool_obj, mock_conn = mock_pool
        mock_conn.execute.return_value = "UPDATE 1"

        with patch("db._pool._pool", mock_pool_obj):
            result = await webhooks.delete_user_webhook(user_id=10)

        assert result is True
        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args[0]
        assert "UPDATE webhooks SET active = FALSE" in call_args[0]

    @pytest.mark.asyncio
    async def test_delete_user_webhook_not_found(self, mock_pool):
        """Test deleting when no webhook exists."""
        from db import webhooks

        mock_pool_obj, mock_conn = mock_pool
        mock_conn.execute.return_value = "UPDATE 0"

        with patch("db._pool._pool", mock_pool_obj):
            result = await webhooks.delete_user_webhook(user_id=10)

        assert result is False

    @pytest.mark.asyncio
    async def test_create_webhook_delivery(self, mock_pool):
        """Test creating a webhook delivery record."""
        from db import webhooks

        mock_pool_obj, mock_conn = mock_pool
        mock_conn.fetchrow.return_value = {
            "id": 1,
            "webhook_id": 5,
            "job_id": 10,
            "status": "pending",
        }

        with patch("db._pool._pool", mock_pool_obj):
            result = await webhooks.create_webhook_delivery(webhook_id=5, job_id=10)

        assert result["webhook_id"] == 5
        assert result["job_id"] == 10
        mock_conn.fetchrow.assert_called_once()
        call_args = mock_conn.fetchrow.call_args[0]
        assert "INSERT INTO webhook_deliveries" in call_args[0]
        assert call_args[1:] == (5, 10)

    @pytest.mark.asyncio
    async def test_update_delivery_status(self, mock_pool):
        """Test updating delivery status."""
        from db import webhooks

        mock_pool_obj, mock_conn = mock_pool

        with patch("db._pool._pool", mock_pool_obj):
            await webhooks.update_delivery_status(
                delivery_id=1,
                status="success",
                http_status=200,
                error_message=None
            )

        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args[0]
        assert "UPDATE webhook_deliveries" in call_args[0]
        assert "attempts = attempts + 1" in call_args[0]
        assert call_args[1:] == (1, "success", 200, None)

    @pytest.mark.asyncio
    async def test_update_delivery_status_with_error(self, mock_pool):
        """Test updating delivery status with error."""
        from db import webhooks

        mock_pool_obj, mock_conn = mock_pool

        with patch("db._pool._pool", mock_pool_obj):
            await webhooks.update_delivery_status(
                delivery_id=1,
                status="failed",
                http_status=500,
                error_message="Server error"
            )

        call_args = mock_conn.execute.call_args[0]
        assert call_args[1:] == (1, "failed", 500, "Server error")


# ============================================================================
# db/outreach.py tests
# ============================================================================

class TestOutreach:
    """Tests for db/outreach.py"""

    @pytest.mark.asyncio
    async def test_save_outreach_draft(self, mock_pool):
        """Test saving an outreach draft."""
        from db import outreach

        mock_pool_obj, mock_conn = mock_pool
        mock_conn.fetchrow.return_value = {"id": 1}
        content = {"subject": "Hello", "body": "World"}

        with patch("db._pool._pool", mock_pool_obj):
            result = await outreach.save_outreach_draft(
                document_id=10,
                user_id=1,
                content=content
            )

        assert result == 1
        mock_conn.fetchrow.assert_called_once()
        call_args = mock_conn.fetchrow.call_args[0]
        assert "INSERT INTO outreach_drafts" in call_args[0]
        assert "ON CONFLICT (document_id)" in call_args[0]
        assert call_args[1:3] == (10, 1)
        # Verify content was JSON serialized
        assert json.loads(call_args[3]) == content

    @pytest.mark.asyncio
    async def test_get_outreach_draft_exists(self, mock_pool):
        """Test getting an existing outreach draft."""
        from db import outreach

        mock_pool_obj, mock_conn = mock_pool
        mock_conn.fetchrow.return_value = {
            "id": 1,
            "document_id": 10,
            "user_id": 1,
            "content": {"subject": "Hello"},
        }

        with patch("db._pool._pool", mock_pool_obj):
            result = await outreach.get_outreach_draft(document_id=10)

        assert result is not None
        assert result["document_id"] == 10
        mock_conn.fetchrow.assert_called_once()
        call_args = mock_conn.fetchrow.call_args[0]
        assert "SELECT * FROM outreach_drafts WHERE document_id = $1" in call_args[0]
        assert call_args[1] == 10

    @pytest.mark.asyncio
    async def test_get_outreach_draft_not_exists(self, mock_pool):
        """Test getting when no draft exists."""
        from db import outreach

        mock_pool_obj, mock_conn = mock_pool
        mock_conn.fetchrow.return_value = None

        with patch("db._pool._pool", mock_pool_obj):
            result = await outreach.get_outreach_draft(document_id=10)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_outreach_drafts_batch(self, mock_pool):
        """Test batch fetching outreach drafts."""
        from db import outreach

        mock_pool_obj, mock_conn = mock_pool
        mock_conn.fetch.return_value = [
            {"document_id": 10, "content": {"subject": "A"}},
            {"document_id": 20, "content": {"subject": "B"}},
        ]

        with patch("db._pool._pool", mock_pool_obj):
            result = await outreach.get_outreach_drafts_batch([10, 20, 30])

        assert len(result) == 2
        assert result[10] == {"subject": "A"}
        assert result[20] == {"subject": "B"}
        assert 30 not in result
        mock_conn.fetch.assert_called_once()
        call_args = mock_conn.fetch.call_args[0]
        assert "SELECT document_id, content FROM outreach_drafts" in call_args[0]
        assert call_args[1] == [10, 20, 30]

    @pytest.mark.asyncio
    async def test_get_outreach_drafts_batch_empty_input(self, mock_pool):
        """Test batch fetching with empty input."""
        from db import outreach

        mock_pool_obj, mock_conn = mock_pool

        with patch("db._pool._pool", mock_pool_obj):
            result = await outreach.get_outreach_drafts_batch([])

        assert result == {}
        mock_conn.fetch.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_outreach_drafts_batch_json_string_content(self, mock_pool):
        """Test batch fetching when content is returned as JSON string."""
        from db import outreach

        mock_pool_obj, mock_conn = mock_pool
        # Simulate content coming back as JSON string
        mock_conn.fetch.return_value = [
            {"document_id": 10, "content": '{"subject": "A"}'},
        ]

        with patch("db._pool._pool", mock_pool_obj):
            result = await outreach.get_outreach_drafts_batch([10])

        assert result[10] == {"subject": "A"}


# ============================================================================
# db/contacts.py tests
# ============================================================================

class TestContacts:
    """Tests for db/contacts.py"""

    @pytest.mark.asyncio
    async def test_save_enriched_contacts(self, mock_pool):
        """Test saving enriched contacts."""
        from db import contacts

        mock_pool_obj, mock_conn = mock_pool
        contacts_data = [
            {
                "name": "John Doe",
                "first_name": "John",
                "last_name": "Doe",
                "title": "CEO",
                "email": "john@example.com",
                "email_status": "valid",
                "profile_url": "https://linkedin.com/in/john",
                "company_name": "Acme Corp",
            },
            {
                "name": "Jane Smith",
                "first_name": "Jane",
                "last_name": "Smith",
                "title": "CTO",
                "email": "jane@example.com",
                "email_status": "valid",
                "profile_url": "https://linkedin.com/in/jane",
                "company_name": "Acme Corp",
            }
        ]

        with patch("db._pool._pool", mock_pool_obj):
            await contacts.save_enriched_contacts(
                document_id=1,
                user_id=10,
                contacts=contacts_data
            )

        mock_conn.executemany.assert_called_once()
        call_args = mock_conn.executemany.call_args[0]
        assert "INSERT INTO enriched_contacts" in call_args[0]

        # Verify the tuples passed for executemany
        tuples = call_args[1]
        assert len(tuples) == 2
        assert tuples[0][0] == 1  # document_id
        assert tuples[0][1] == 10  # user_id
        assert tuples[0][2] == "John Doe"  # name
        assert tuples[1][2] == "Jane Smith"

    @pytest.mark.asyncio
    async def test_save_enriched_contacts_empty_list(self, mock_pool):
        """Test saving empty contacts list."""
        from db import contacts

        mock_pool_obj, mock_conn = mock_pool

        with patch("db._pool._pool", mock_pool_obj):
            await contacts.save_enriched_contacts(
                document_id=1,
                user_id=10,
                contacts=[]
            )

        # executemany with empty list should still be called
        mock_conn.executemany.assert_called_once()
        call_args = mock_conn.executemany.call_args[0]
        assert call_args[1] == []

    @pytest.mark.asyncio
    async def test_get_enriched_contacts(self, mock_pool):
        """Test getting enriched contacts."""
        from db import contacts

        mock_pool_obj, mock_conn = mock_pool
        mock_conn.fetch.return_value = [
            {
                "id": 1,
                "document_id": 1,
                "user_id": 10,
                "name": "John Doe",
                "first_name": "John",
                "last_name": "Doe",
                "title": "CEO",
                "email": "john@example.com",
                "email_status": "valid",
                "profile_url": "https://linkedin.com/in/john",
                "company_name": "Acme Corp",
            }
        ]

        with patch("db._pool._pool", mock_pool_obj):
            result = await contacts.get_enriched_contacts(document_id=1, user_id=10)

        assert len(result) == 1
        assert result[0]["name"] == "John Doe"
        assert result[0]["email"] == "john@example.com"
        mock_conn.fetch.assert_called_once()
        call_args = mock_conn.fetch.call_args[0]
        assert "SELECT * FROM enriched_contacts WHERE document_id = $1 AND user_id = $2" in call_args[0]
        assert call_args[1:] == (1, 10)

    @pytest.mark.asyncio
    async def test_get_enriched_contacts_empty(self, mock_pool):
        """Test getting when no contacts exist."""
        from db import contacts

        mock_pool_obj, mock_conn = mock_pool
        mock_conn.fetch.return_value = []

        with patch("db._pool._pool", mock_pool_obj):
            result = await contacts.get_enriched_contacts(document_id=1, user_id=10)

        assert result == []


# ============================================================================
# db/documents.py tests
# ============================================================================

class TestDocuments:
    """Tests for db/documents.py"""

    def _make_test_document(self, **overrides):
        """Helper to create a test ResearchDocument."""
        defaults = {
            "company_url": "https://example.com",
            "company_name": "Acme Corp",
            "created_at": datetime(2024, 1, 1),
            "company_overview": "Overview",
            "projects_initiatives": "Projects",
            "confirmed_tech_stack": "Python",
            "hiring_signals": "Hiring",
            "business_problems": "Problems",
            "existential_data_points": "Data",
            "product_fit": "Fit",
            "talking_points": "Points",
            "recent_news": "",
            "key_contacts": "Contacts",
            "information_gaps": "Gaps",
            "opportunity_score": 8,
            "pain_score": 7,
            "fit_score": 9,
            "timing_score": 6,
            "score_summary": "Summary",
            "pain_evidence": "Pain evidence",
            "fit_evidence": "Fit evidence",
            "timing_evidence": "Timing evidence",
            "thinking_content": "Thinking",
            "model_used": "claude-3",
            "full_markdown": "# Full markdown",
        }
        defaults.update(overrides)
        return ResearchDocument(**defaults)

    @pytest.mark.asyncio
    async def test_save_document(self, mock_pool):
        """Test saving a document."""
        from db import documents

        mock_pool_obj, mock_conn = mock_pool
        mock_conn.fetchrow.return_value = {"id": 123}

        doc = self._make_test_document()

        with patch("db._pool._pool", mock_pool_obj):
            result = await documents.save_document(doc, user_id=1)

        assert result == 123
        mock_conn.fetchrow.assert_called_once()
        call_args = mock_conn.fetchrow.call_args[0]
        assert "INSERT INTO research_documents" in call_args[0]
        # Verify user_id is first param
        assert call_args[1] == 1
        # Verify company_url is second param
        assert call_args[2] == "https://example.com"

    @pytest.mark.asyncio
    async def test_get_document_exists(self, mock_pool):
        """Test getting an existing document."""
        from db import documents

        mock_pool_obj, mock_conn = mock_pool
        mock_conn.fetchrow.return_value = {
            "id": 1,
            "company_url": "https://example.com",
            "company_name": "Acme Corp",
            "created_at": datetime(2024, 1, 1),
            "company_overview": "Overview",
            "projects_initiatives": "Projects",
            "confirmed_tech_stack": "Python",
            "hiring_signals": "Hiring",
            "business_problems": "Problems",
            "existential_data_points": "Data",
            "product_fit": "Fit",
            "talking_points": "Points",
            "recent_news": "",
            "key_contacts": "Contacts",
            "information_gaps": "Gaps",
            "opportunity_score": 8,
            "pain_score": 7,
            "fit_score": 9,
            "timing_score": 6,
            "score_summary": "Summary",
            "pain_evidence": "Pain",
            "fit_evidence": "Fit",
            "timing_evidence": "Timing",
            "thinking_content": "Thinking",
            "model_used": "claude-3",
            "full_markdown": "# Full",
        }

        with patch("db._pool._pool", mock_pool_obj):
            result = await documents.get_document(doc_id=1, user_id=10)

        assert result is not None
        assert isinstance(result, ResearchDocument)
        assert result.company_name == "Acme Corp"
        assert result.opportunity_score == 8
        mock_conn.fetchrow.assert_called_once()
        call_args = mock_conn.fetchrow.call_args[0]
        assert "SELECT * FROM research_documents WHERE id = $1 AND user_id = $2" in call_args[0]
        assert call_args[1:] == (1, 10)

    @pytest.mark.asyncio
    async def test_get_document_not_exists(self, mock_pool):
        """Test getting a non-existent document."""
        from db import documents

        mock_pool_obj, mock_conn = mock_pool
        mock_conn.fetchrow.return_value = None

        with patch("db._pool._pool", mock_pool_obj):
            result = await documents.get_document(doc_id=999, user_id=10)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_all_documents(self, mock_pool):
        """Test getting all documents for a user."""
        from db import documents

        mock_pool_obj, mock_conn = mock_pool
        mock_conn.fetch.return_value = [
            {
                "id": 1,
                "user_id": 10,
                "company_url": "https://example.com",
                "company_name": "Acme Corp",
                "created_at": datetime(2024, 1, 1),
                "company_overview": "Overview",
                "projects_initiatives": "Projects",
                "confirmed_tech_stack": "Python",
                "hiring_signals": "Hiring",
                "business_problems": "Problems",
                "existential_data_points": "Data",
                "product_fit": "Fit",
                "talking_points": "Points",
                "recent_news": "",
                "key_contacts": "Contacts",
                "information_gaps": "Gaps",
                "opportunity_score": 8,
                "pain_score": 7,
                "fit_score": 9,
                "timing_score": 6,
                "score_summary": "Summary",
                "pain_evidence": "Pain",
                "fit_evidence": "Fit",
                "timing_evidence": "Timing",
                "thinking_content": "Thinking",
                "model_used": "claude-3",
            }
        ]

        with patch("db._pool._pool", mock_pool_obj):
            result = await documents.get_all_documents(user_id=10, limit=50)

        assert len(result) == 1
        assert isinstance(result[0], ResearchDocument)
        assert result[0].company_name == "Acme Corp"
        # Summary should not include full_markdown
        assert result[0].full_markdown == ""
        mock_conn.fetch.assert_called_once()
        call_args = mock_conn.fetch.call_args[0]
        assert call_args[1:] == (10, 50)

    @pytest.mark.asyncio
    async def test_get_recent_document_by_url_exists(self, mock_pool):
        """Test getting a recent document id by URL."""
        from db import documents

        mock_pool_obj, mock_conn = mock_pool
        mock_conn.fetchrow.return_value = {"id": 42}

        with patch("db._pool._pool", mock_pool_obj):
            result = await documents.get_recent_document_by_url(
                user_id=10,
                company_url="https://example.com",
                hours=24
            )

        assert result == 42
        mock_conn.fetchrow.assert_called_once()
        call_args = mock_conn.fetchrow.call_args[0]
        assert "make_interval(hours => $3)" in call_args[0]
        assert call_args[1:] == (10, "https://example.com", 24)

    @pytest.mark.asyncio
    async def test_get_recent_document_by_url_not_exists(self, mock_pool):
        """Test getting when no recent document exists."""
        from db import documents

        mock_pool_obj, mock_conn = mock_pool
        mock_conn.fetchrow.return_value = None

        with patch("db._pool._pool", mock_pool_obj):
            result = await documents.get_recent_document_by_url(
                user_id=10,
                company_url="https://example.com",
                hours=24
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_check_duplicate_research_exists(self, mock_pool):
        """Test checking for duplicate research."""
        from db import documents

        mock_pool_obj, mock_conn = mock_pool
        mock_conn.fetchrow.return_value = {
            "id": 1,
            "company_name": "Acme Corp",
            "created_at": datetime(2024, 1, 1),
        }

        with patch("db._pool._pool", mock_pool_obj):
            result = await documents.check_duplicate_research(
                user_id=10,
                company_url="https://example.com",
                days=7
            )

        assert result is not None
        assert result["company_name"] == "Acme Corp"
        mock_conn.fetchrow.assert_called_once()
        call_args = mock_conn.fetchrow.call_args[0]
        assert "make_interval(days => $3)" in call_args[0]
        assert call_args[1:] == (10, "https://example.com", 7)

    @pytest.mark.asyncio
    async def test_check_duplicate_research_not_exists(self, mock_pool):
        """Test checking when no duplicate exists."""
        from db import documents

        mock_pool_obj, mock_conn = mock_pool
        mock_conn.fetchrow.return_value = None

        with patch("db._pool._pool", mock_pool_obj):
            result = await documents.check_duplicate_research(
                user_id=10,
                company_url="https://example.com",
                days=7
            )

        assert result is None
