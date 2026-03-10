import os
from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest

import main


class _FakeConn:
    async def fetchval(self, query):
        return 1


class _FakePool:
    @asynccontextmanager
    async def acquire(self):
        yield _FakeConn()

    def get_size(self):
        return 4

    def get_idle_size(self):
        return 1


@pytest.mark.asyncio
async def test_health_returns_ok_with_live_pool(async_client):
    with patch.object(main.db_pool_module, "_pool", _FakePool()):
        response = await async_client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "db": "ok",
        "pool": {"size": 4, "free": 1, "used": 3},
    }


@pytest.mark.asyncio
async def test_health_returns_degraded_when_pool_unavailable(async_client):
    with patch.object(main.db_pool_module, "_pool", None):
        response = await async_client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "db": "error"}


@pytest.mark.asyncio
async def test_version_reports_deploy_metadata(async_client):
    with patch.dict(
        os.environ,
        {
            "RAILWAY_GIT_COMMIT_SHA": "75b3b63",
            "RAILWAY_DEPLOYMENT_ID": "deploy_123",
        },
        clear=False,
    ):
        response = await async_client.get("/version")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "app_version": "1.0.0",
        "environment": "development",
        "git_commit": "75b3b63",
        "git_commit_source": "RAILWAY_GIT_COMMIT_SHA",
        "deployment_id": "deploy_123",
        "deployment_id_source": "RAILWAY_DEPLOYMENT_ID",
    }
