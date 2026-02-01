"""Tests for fan-out jobs, failure alerts, and admin queue endpoint."""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch, MagicMock


# ---------------------------------------------------------------------------
# 1. Fan-out: run_bulk_job enqueues bulk_item tasks
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_bulk_job_enqueues_children():
    items = [
        {"id": 10, "company_url": "https://a.com"},
        {"id": 11, "company_url": "https://b.com"},
    ]
    with patch("api.jobs.get_bulk_job_items", new_callable=AsyncMock, return_value=items), \
         patch("db.task_queue.enqueue_many", new_callable=AsyncMock, return_value=2) as mock_enqueue_many:
        from api.jobs import run_bulk_job
        await run_bulk_job(bulk_job_id=5, user_id=1, api_key_id=2, is_admin=False)

        assert mock_enqueue_many.call_count == 1
        call_args = mock_enqueue_many.call_args
        assert call_args[0][0] == "bulk_item"
        assert call_args[0][1][0]["bulk_job_id"] == 5
        assert call_args[0][1][0]["item_id"] == 10


@pytest.mark.asyncio
async def test_run_list_analysis_enqueues_children():
    accounts = [
        {"id": 20, "company_url": "https://c.com"},
    ]
    with patch("api.jobs.get_pending_list_accounts", new_callable=AsyncMock, return_value=accounts), \
         patch("db.task_queue.enqueue_many", new_callable=AsyncMock, return_value=1) as mock_enqueue_many:
        from api.jobs import run_list_analysis
        await run_list_analysis(list_id=3, user_id=1)

        assert mock_enqueue_many.call_count == 1
        assert mock_enqueue_many.call_args[0][0] == "list_item"
        assert mock_enqueue_many.call_args[0][1][0]["account_id"] == 20


# ---------------------------------------------------------------------------
# 2. Failure alerts
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fail_returns_exhausted_flag():
    """fail() should return True when retries are exhausted."""
    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(return_value={"exhausted": True})
    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch("db._pool._pool", mock_pool):
        from db.task_queue import fail
        result = await fail(1, "boom")
        assert result is True


@pytest.mark.asyncio
async def test_send_task_failure_alert_noop_when_no_url():
    """Alert should be a no-op when slack_webhook_url is empty."""
    mock_settings = MagicMock()
    mock_settings.slack_webhook_url = ""
    with patch("config.get_settings", return_value=mock_settings):
        from services.notifications import send_task_failure_alert
        # Should not raise
        await send_task_failure_alert(1, "research", "some error")


@pytest.mark.asyncio
async def test_send_task_failure_alert_posts_to_slack():
    mock_settings = MagicMock()
    mock_settings.slack_webhook_url = "https://hooks.slack.com/test"

    mock_response = MagicMock()
    mock_response.status_code = 200

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("config.get_settings", return_value=mock_settings), \
         patch("services.notifications.httpx.AsyncClient", return_value=mock_client):
        from services.notifications import send_task_failure_alert
        await send_task_failure_alert(42, "research", "connection timeout")

        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert call_args[0][0] == "https://hooks.slack.com/test"
        body = call_args[1]["json"]
        assert "42" in str(body)


# ---------------------------------------------------------------------------
# 3. Admin queue endpoint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_admin_queue_requires_auth(async_client):
    with patch("auth.get_current_user", new_callable=AsyncMock, return_value=None), \
         patch("auth.get_user_usage", new_callable=AsyncMock, return_value=None):
        resp = await async_client.get("/admin/queue")
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_admin_queue_requires_admin(async_client):
    user = {"id": 1, "email": "user@test.com"}
    with patch("auth.get_current_user", new_callable=AsyncMock, return_value=user), \
         patch("auth.get_user_usage", new_callable=AsyncMock, return_value={"is_admin": False}):
        resp = await async_client.get("/admin/queue")
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_admin_queue_returns_stats(async_client):
    user = {"id": 1, "email": "admin@test.com"}
    stats = {"pending": 5, "running": 2, "completed": 100, "failed": 3}
    with patch("auth.get_current_user", new_callable=AsyncMock, return_value=user), \
         patch("auth.get_user_usage", new_callable=AsyncMock, return_value={"is_admin": True}), \
         patch("routes.admin.get_queue_stats", new_callable=AsyncMock, return_value=stats):
        resp = await async_client.get("/admin/queue")
        assert resp.status_code == 200
        data = resp.json()
        assert data["pending"] == 5
        assert data["failed"] == 3


# ---------------------------------------------------------------------------
# 4. check_no_pending_siblings / get_queue_stats
# ---------------------------------------------------------------------------

def _make_locked_mock_pool(fetchrow_side_effects):
    """Build a mock pool whose conn supports transaction(), execute(), fetchrow()."""
    call_count = {"i": 0}
    async def _fetchrow(*args, **kwargs):
        idx = call_count["i"]
        call_count["i"] += 1
        return fetchrow_side_effects[idx]

    mock_conn = AsyncMock()
    mock_conn.fetchrow = _fetchrow
    mock_conn.execute = AsyncMock()
    mock_txn = AsyncMock()
    mock_txn.__aenter__ = AsyncMock(return_value=mock_txn)
    mock_txn.__aexit__ = AsyncMock(return_value=False)
    mock_conn.transaction = MagicMock(return_value=mock_txn)
    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return mock_pool, mock_conn


@pytest.mark.asyncio
async def test_check_no_pending_siblings_returns_true_when_zero():
    """Should return True and insert marker when count is 0 and no prior marker."""
    # First fetchrow: check existing marker → None; second: count → 0
    mock_pool, mock_conn = _make_locked_mock_pool([None, {"cnt": 0}])

    with patch("db._pool._pool", mock_pool):
        from db.task_queue import check_no_pending_siblings
        result = await check_no_pending_siblings("bulk_job_id", "5", 5)
        assert result is True
        # Verify advisory lock + marker insert happened
        execute_calls = [c[0][0] for c in mock_conn.execute.call_args_list]
        assert any("pg_advisory_xact_lock" in s for s in execute_calls)
        assert any("INSERT INTO task_queue" in s for s in execute_calls)


@pytest.mark.asyncio
async def test_check_no_pending_siblings_returns_false_when_remaining():
    """Should return False when siblings remain."""
    mock_pool, _ = _make_locked_mock_pool([None, {"cnt": 2}])

    with patch("db._pool._pool", mock_pool):
        from db.task_queue import check_no_pending_siblings
        result = await check_no_pending_siblings("list_id", "3", 3)
        assert result is False


@pytest.mark.asyncio
async def test_check_no_pending_siblings_returns_false_when_marker_exists():
    """Should return False if finalization marker already exists (another child won)."""
    mock_pool, _ = _make_locked_mock_pool([{"id": 99}])  # marker exists

    with patch("db._pool._pool", mock_pool):
        from db.task_queue import check_no_pending_siblings
        result = await check_no_pending_siblings("bulk_job_id", "5", 5)
        assert result is False


@pytest.mark.asyncio
async def test_get_queue_stats():
    rows = [
        {"status": "pending", "cnt": 10},
        {"status": "completed", "cnt": 50},
    ]
    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=rows)
    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch("db._pool._pool", mock_pool):
        from db.task_queue import get_queue_stats
        result = await get_queue_stats()
        assert result == {"pending": 10, "completed": 50}
        sql = mock_conn.fetch.call_args[0][0]
        assert "_finalize_" in sql
