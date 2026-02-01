"""Tests for worker.py"""

import asyncio
import pytest
from unittest.mock import patch, MagicMock, AsyncMock


@pytest.fixture(autouse=True)
def mock_settings():
    with patch("config.get_settings") as m:
        m.return_value = MagicMock(worker_poll_interval=1, worker_concurrency=2)
        yield m


@pytest.fixture
def worker_module(mock_settings):
    import worker
    worker._shutdown = asyncio.Event()
    return worker


class TestHandleSignal:
    def test_sets_shutdown_event(self, worker_module):
        assert not worker_module._shutdown.is_set()
        worker_module._handle_signal()
        assert worker_module._shutdown.is_set()


class TestDispatch:
    @pytest.mark.asyncio
    async def test_dispatch_research_task(self, worker_module):
        task = {"id": 1, "task_type": "research", "payload": {"account_id": "a1"}}
        mock_tq = MagicMock()
        mock_tq.complete = AsyncMock()

        with patch("db.task_queue", mock_tq, create=True), \
             patch("api.jobs.run_research_job", new_callable=AsyncMock) as mock_job:
            await worker_module._dispatch(task)
            mock_job.assert_called_once_with(account_id="a1")
            mock_tq.complete.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_dispatch_bulk_task(self, worker_module):
        task = {"id": 2, "task_type": "bulk", "payload": {"bulk_id": "b1"}}
        mock_tq = MagicMock()
        mock_tq.complete = AsyncMock()

        with patch("db.task_queue", mock_tq, create=True), \
             patch("api.jobs.run_bulk_job", new_callable=AsyncMock) as mock_job:
            await worker_module._dispatch(task)
            mock_job.assert_called_once_with(bulk_id="b1")
            mock_tq.complete.assert_called_once_with(2)

    @pytest.mark.asyncio
    async def test_dispatch_automation_task(self, worker_module):
        task = {"id": 3, "task_type": "automation", "payload": {"user_id": "u1", "trigger_event": "ev", "context": {"k": "v"}}}
        mock_tq = MagicMock()
        mock_tq.complete = AsyncMock()

        with patch("db.task_queue", mock_tq, create=True), \
             patch("services.automation.evaluate_rules", new_callable=AsyncMock) as mock_job:
            await worker_module._dispatch(task)
            mock_job.assert_called_once_with("u1", "ev", {"k": "v"})
            mock_tq.complete.assert_called_once_with(3)

    @pytest.mark.asyncio
    async def test_dispatch_retry_task(self, worker_module):
        task = {"id": 4, "task_type": "retry", "payload": {"account_id": "a2"}}
        mock_tq = MagicMock()
        mock_tq.complete = AsyncMock()

        with patch("db.task_queue", mock_tq, create=True), \
             patch("api.jobs.run_retry_account", new_callable=AsyncMock) as mock_job:
            await worker_module._dispatch(task)
            mock_job.assert_called_once_with(account_id="a2")
            mock_tq.complete.assert_called_once_with(4)

    @pytest.mark.asyncio
    async def test_dispatch_list_analysis_task(self, worker_module):
        task = {"id": 5, "task_type": "list_analysis", "payload": {"list_id": "l1"}}
        mock_tq = MagicMock()
        mock_tq.complete = AsyncMock()

        with patch("db.task_queue", mock_tq, create=True), \
             patch("api.jobs.run_list_analysis", new_callable=AsyncMock) as mock_job:
            await worker_module._dispatch(task)
            mock_job.assert_called_once_with(list_id="l1")
            mock_tq.complete.assert_called_once_with(5)

    @pytest.mark.asyncio
    async def test_dispatch_bulk_item_task(self, worker_module):
        task = {"id": 6, "task_type": "bulk_item", "payload": {"item_id": "i1"}}
        mock_tq = MagicMock()
        mock_tq.complete = AsyncMock()

        with patch("db.task_queue", mock_tq, create=True), \
             patch("api.jobs.run_bulk_item", new_callable=AsyncMock) as mock_job:
            await worker_module._dispatch(task)
            mock_job.assert_called_once_with(item_id="i1")
            mock_tq.complete.assert_called_once_with(6)

    @pytest.mark.asyncio
    async def test_dispatch_list_item_task(self, worker_module):
        task = {"id": 7, "task_type": "list_item", "payload": {"item_id": "i2"}}
        mock_tq = MagicMock()
        mock_tq.complete = AsyncMock()

        with patch("db.task_queue", mock_tq, create=True), \
             patch("api.jobs.run_list_item", new_callable=AsyncMock) as mock_job:
            await worker_module._dispatch(task)
            mock_job.assert_called_once_with(item_id="i2")
            mock_tq.complete.assert_called_once_with(7)

    @pytest.mark.asyncio
    async def test_dispatch_batch_write_task(self, worker_module):
        task = {"id": 8, "task_type": "batch_write", "payload": {"batch_id": "b1"}}
        mock_tq = MagicMock()
        mock_tq.complete = AsyncMock()

        with patch("db.task_queue", mock_tq, create=True), \
             patch("api.jobs.run_batch_write_sequences", new_callable=AsyncMock) as mock_job:
            await worker_module._dispatch(task)
            mock_job.assert_called_once_with(batch_id="b1")
            mock_tq.complete.assert_called_once_with(8)

    @pytest.mark.asyncio
    async def test_dispatch_unknown_task_type(self, worker_module):
        task = {"id": 9, "task_type": "unknown", "payload": {}}
        mock_tq = MagicMock()
        mock_tq.fail = AsyncMock(return_value=False)

        with patch("db.task_queue", mock_tq, create=True):
            await worker_module._dispatch(task)
            mock_tq.fail.assert_called_once()

    @pytest.mark.asyncio
    async def test_dispatch_failure_marks_task_failed(self, worker_module):
        task = {"id": 10, "task_type": "research", "payload": {"account_id": "a1"}}
        mock_tq = MagicMock()
        mock_tq.fail = AsyncMock(return_value=False)

        with patch("db.task_queue", mock_tq, create=True), \
             patch("api.jobs.run_research_job", new_callable=AsyncMock, side_effect=Exception("boom")):
            await worker_module._dispatch(task)
            mock_tq.fail.assert_called_once_with(10, "boom")

    @pytest.mark.asyncio
    async def test_dispatch_exhausted_research_refunds(self, worker_module):
        task = {"id": 11, "task_type": "research", "payload": {"user_id": "u1", "account_id": "a1"}}
        mock_tq = MagicMock()
        mock_tq.fail = AsyncMock(return_value=True)

        with patch("db.task_queue", mock_tq, create=True), \
             patch("api.jobs.run_research_job", new_callable=AsyncMock, side_effect=Exception("fail")), \
             patch("database.refund_credit", new_callable=AsyncMock) as mock_refund, \
             patch("services.notifications.send_task_failure_alert", new_callable=AsyncMock):
            await worker_module._dispatch(task)
            mock_refund.assert_called_once_with("u1")

    @pytest.mark.asyncio
    async def test_dispatch_exhausted_admin_no_refund(self, worker_module):
        task = {"id": 12, "task_type": "research", "payload": {"user_id": "u1", "is_admin": True}}
        mock_tq = MagicMock()
        mock_tq.fail = AsyncMock(return_value=True)

        with patch("db.task_queue", mock_tq, create=True), \
             patch("api.jobs.run_research_job", new_callable=AsyncMock, side_effect=Exception("fail")), \
             patch("database.refund_credit", new_callable=AsyncMock) as mock_refund, \
             patch("services.notifications.send_task_failure_alert", new_callable=AsyncMock):
            await worker_module._dispatch(task)
            mock_refund.assert_not_called()

    @pytest.mark.asyncio
    async def test_dispatch_exhausted_sends_alert(self, worker_module):
        task = {"id": 13, "task_type": "bulk", "payload": {"bulk_id": "b1"}}
        mock_tq = MagicMock()
        mock_tq.fail = AsyncMock(return_value=True)

        with patch("db.task_queue", mock_tq, create=True), \
             patch("api.jobs.run_bulk_job", new_callable=AsyncMock, side_effect=Exception("fail")), \
             patch("services.notifications.send_task_failure_alert", new_callable=AsyncMock) as mock_alert:
            await worker_module._dispatch(task)
            mock_alert.assert_called_once_with(13, "bulk", "fail")

    @pytest.mark.asyncio
    async def test_dispatch_exhausted_non_research_no_refund(self, worker_module):
        task = {"id": 14, "task_type": "bulk", "payload": {"bulk_id": "b1"}}
        mock_tq = MagicMock()
        mock_tq.fail = AsyncMock(return_value=True)

        with patch("db.task_queue", mock_tq, create=True), \
             patch("api.jobs.run_bulk_job", new_callable=AsyncMock, side_effect=Exception("fail")), \
             patch("database.refund_credit", new_callable=AsyncMock, create=True) as mock_refund, \
             patch("services.notifications.send_task_failure_alert", new_callable=AsyncMock):
            await worker_module._dispatch(task)
            mock_refund.assert_not_called()


class TestMain:
    @pytest.mark.asyncio
    async def test_main_initializes_database(self, worker_module):
        with patch("db._pool.init_database", new_callable=AsyncMock) as mock_init, \
             patch("db._pool.close_database", new_callable=AsyncMock) as mock_close, \
             patch.object(worker_module, "_poll_loop", new_callable=AsyncMock), \
             patch("asyncio.get_event_loop") as mock_loop:
            mock_loop.return_value = MagicMock()
            await worker_module.main()
            mock_init.assert_called_once()
            mock_close.assert_called_once()

    @pytest.mark.asyncio
    async def test_main_closes_database_on_error(self, worker_module):
        with patch("db._pool.init_database", new_callable=AsyncMock), \
             patch("db._pool.close_database", new_callable=AsyncMock) as mock_close, \
             patch.object(worker_module, "_poll_loop", new_callable=AsyncMock, side_effect=Exception("err")), \
             patch("asyncio.get_event_loop") as mock_loop:
            mock_loop.return_value = MagicMock()
            with pytest.raises(Exception, match="err"):
                await worker_module.main()
            mock_close.assert_called_once()
