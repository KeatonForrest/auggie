"""Tests for auth hotfix: provider-ID lookups return email, invite auto-accept works."""

import pytest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch, MagicMock


def _make_pool_mock(conn):
    """Build a mock pool whose .acquire() works as an async context manager."""
    @asynccontextmanager
    async def _acquire():
        yield conn

    mock_pool = MagicMock()
    mock_pool.acquire = _acquire
    return mock_pool


class TestProviderLookupReturnsEmail:
    """Patch 4: provider-ID lookups must return full user row (incl. email)."""

    @pytest.mark.asyncio
    async def test_google_lookup_returns_email(self):
        """get_user_by_google_id returns dict with 'email' key."""
        fake_row = {
            "id": 1, "org_id": 10, "email": "alice@example.com",
            "name": "Alice", "google_id": "g-123",
        }
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=fake_row)

        with patch("db.users._db._pool", _make_pool_mock(mock_conn)):
            from db.users import get_user_by_google_id
            result = await get_user_by_google_id("g-123")

        assert result is not None
        assert "email" in result
        assert result["email"] == "alice@example.com"
        # Verify query uses SELECT * (not SELECT id, org_id)
        query = mock_conn.fetchrow.call_args[0][0]
        assert "SELECT *" in query

    @pytest.mark.asyncio
    async def test_microsoft_lookup_returns_email(self):
        """get_user_by_microsoft_id returns dict with 'email' key."""
        fake_row = {
            "id": 2, "org_id": 20, "email": "bob@example.com",
            "name": "Bob", "microsoft_id": "ms-456",
        }
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=fake_row)

        with patch("db.users._db._pool", _make_pool_mock(mock_conn)):
            from db.users import get_user_by_microsoft_id
            result = await get_user_by_microsoft_id("ms-456")

        assert result is not None
        assert "email" in result
        assert result["email"] == "bob@example.com"
        query = mock_conn.fetchrow.call_args[0][0]
        assert "SELECT *" in query

    @pytest.mark.asyncio
    async def test_google_lookup_not_found(self):
        """get_user_by_google_id returns None for unknown ID."""
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=None)

        with patch("db.users._db._pool", _make_pool_mock(mock_conn)):
            from db.users import get_user_by_google_id
            result = await get_user_by_google_id("unknown")

        assert result is None


class TestAutoAcceptInvites:
    """Patch 5: _auto_accept_invites works with full user row."""

    @pytest.mark.asyncio
    async def test_auto_accept_with_email(self):
        """_auto_accept_invites succeeds when user dict has email."""
        user = {"id": 1, "email": "alice@example.com", "org_id": 10}
        fake_invite = {"token": "tok-abc", "org_name": "Acme Corp"}

        with patch("auth.get_pending_invites_for_email", new_callable=AsyncMock, return_value=[fake_invite]) as mock_get, \
             patch("auth.accept_invite", new_callable=AsyncMock) as mock_accept:
            from auth import _auto_accept_invites
            await _auto_accept_invites(user)

        mock_get.assert_awaited_once_with("alice@example.com")
        mock_accept.assert_awaited_once_with("tok-abc", 1)

    @pytest.mark.asyncio
    async def test_auto_accept_no_pending(self):
        """_auto_accept_invites is a no-op when no invites exist."""
        user = {"id": 1, "email": "alice@example.com", "org_id": 10}

        with patch("auth.get_pending_invites_for_email", new_callable=AsyncMock, return_value=[]) as mock_get, \
             patch("auth.accept_invite", new_callable=AsyncMock) as mock_accept:
            from auth import _auto_accept_invites
            await _auto_accept_invites(user)

        mock_get.assert_awaited_once_with("alice@example.com")
        mock_accept.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_auto_accept_missing_email_key_errors(self):
        """_auto_accept_invites logs error (not crash) when email is missing."""
        user = {"id": 1, "org_id": 10}  # no email key

        with patch("auth.get_pending_invites_for_email", new_callable=AsyncMock) as mock_get:
            from auth import _auto_accept_invites
            # Should not raise — error is caught and logged
            await _auto_accept_invites(user)

        # get_pending_invites_for_email should NOT have been called (KeyError before it)
        mock_get.assert_not_awaited()
