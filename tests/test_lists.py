"""test_lists.py - List route tests."""

import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_pipeline_status(authed_client):
    """GET /lists/{id}/pipeline-status returns JSON counts."""
    with patch("routes.lists.get_list", new_callable=AsyncMock) as mock_list, \
         patch("routes.lists.get_pipeline_counts", new_callable=AsyncMock) as mock_counts:
        mock_list.return_value = {"id": 1, "name": "Test"}
        mock_counts.return_value = {
            "total": 10, "scored": 8, "enriched": 5,
            "sequences_written": 3, "pushed": 1,
        }

        response = await authed_client.get("/lists/1/pipeline-status")

        assert response.status_code == 200
        data = response.json()
        assert data["scored"] == 8
        assert data["enriched"] == 5
        assert data["total"] == 10


@pytest.mark.asyncio
async def test_view_list(authed_client):
    """GET /lists/{id} returns 200 with pipeline counts."""
    with patch("routes.lists.get_list", new_callable=AsyncMock) as mock_list, \
         patch("routes.lists.get_list_accounts", new_callable=AsyncMock) as mock_accounts, \
         patch("routes.lists.get_user_usage", new_callable=AsyncMock) as mock_usage, \
         patch("routes.lists.get_integration", new_callable=AsyncMock) as mock_integration, \
         patch("routes.lists.get_pipeline_counts", new_callable=AsyncMock) as mock_counts:
        mock_list.return_value = {"id": 1, "name": "Test List", "status": "completed",
                                   "total_accounts": 5, "analyzed_accounts": 5,
                                   "failed_accounts": 0, "credits_reserved": 500}
        mock_accounts.return_value = [
            {"id": 1, "company_url": "https://example.com", "status": "completed",
             "pain_score": 80, "fit_score": 70, "timing_score": 60, "composite_score": 70,
             "company_name": "Example Corp", "document_id": 1}
        ]
        mock_usage.return_value = {"bonus_credits": 1000, "is_admin": False}
        mock_integration.return_value = None
        mock_counts.return_value = {
            "total": 5, "scored": 5, "enriched": 2,
            "sequences_written": 1, "pushed": 0,
        }

        response = await authed_client.get("/lists/1")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]


@pytest.mark.asyncio
async def test_batch_write_sequences(authed_client):
    """POST /lists/{id}/batch-write-sequences queues writing and returns count."""
    with patch("routes.lists.get_list", new_callable=AsyncMock) as mock_list, \
         patch("routes.lists.count_ready_accounts", new_callable=AsyncMock) as mock_count, \
         patch("routes.lists.create_tracked_task", new_callable=AsyncMock) as mock_task:
        mock_list.return_value = {"id": 1, "name": "Test"}
        mock_count.return_value = 7

        response = await authed_client.post(
            "/lists/1/batch-write-sequences",
            json={},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["queued_count"] == 7
        assert data["success"] is True


@pytest.mark.asyncio
async def test_retry_selected(authed_client):
    """POST /lists/{id}/retry-selected retries failed accounts."""
    with patch("routes.lists.get_list", new_callable=AsyncMock) as mock_list, \
         patch("routes.lists.get_list_accounts", new_callable=AsyncMock) as mock_accounts, \
         patch("routes.lists.get_user_usage", new_callable=AsyncMock) as mock_usage, \
         patch("routes.lists.use_credit", new_callable=AsyncMock) as mock_use, \
         patch("routes.lists.reset_list_account", new_callable=AsyncMock), \
         patch("routes.lists.create_research_job", new_callable=AsyncMock) as mock_job, \
         patch("routes.lists.update_list_account", new_callable=AsyncMock), \
         patch("routes.lists.create_tracked_task", new_callable=AsyncMock):
        mock_list.return_value = {"id": 1, "name": "Test"}
        mock_accounts.return_value = [
            {"id": 10, "company_url": "https://fail.com", "status": "failed"},
            {"id": 11, "company_url": "https://fail2.com", "status": "failed"},
        ]
        mock_usage.return_value = {"bonus_credits": 10000, "is_admin": False}
        mock_use.return_value = True
        mock_job.return_value = {"id": 99}

        response = await authed_client.post(
            "/lists/1/retry-selected",
            json={"account_ids": [10, 11]},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["retried"] == 2


@pytest.mark.asyncio
async def test_export_selected(authed_client):
    """POST /lists/{id}/export-selected returns CSV."""
    with patch("routes.lists.get_list", new_callable=AsyncMock) as mock_list, \
         patch("routes.lists.get_list_accounts", new_callable=AsyncMock) as mock_accounts:
        mock_list.return_value = {"id": 1, "name": "Test"}
        mock_accounts.return_value = [
            {"company_name": "Acme", "company_url": "https://acme.com",
             "pain_score": 90, "fit_score": 80, "timing_score": 70,
             "composite_score": 80, "status": "completed"},
        ]

        response = await authed_client.post(
            "/lists/1/export-selected",
            json={"account_ids": [1]},
        )

        assert response.status_code == 200
        assert "text/csv" in response.headers["content-type"]
        assert "Acme" in response.text
