"""Tests for db/tech_signals.py"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from models import TechStack, DetectedTechnology, InfrastructureSignals, JobSignals, TechMention, PainInference


@pytest.fixture
def mock_conn():
    conn = AsyncMock()
    conn.executemany = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    return conn


@pytest.fixture
def mock_get_connection(mock_conn):
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _get():
        yield mock_conn

    return _get


class TestSaveTechSignals:
    @pytest.mark.asyncio
    async def test_saves_tech_detection_signals(self, mock_get_connection, mock_conn):
        with patch("db.tech_signals.get_connection", mock_get_connection):
            from db.tech_signals import save_tech_signals
            tech = TechStack(technologies=[
                DetectedTechnology(name="React", version="18", category="JS", confidence=100),
                DetectedTechnology(name="Nginx", version=None, category="Web servers", confidence=100),
            ])
            count = await save_tech_signals(1, {"example.com": tech})
        assert count == 2
        mock_conn.executemany.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_saves_dns_signals(self, mock_get_connection, mock_conn):
        with patch("db.tech_signals.get_connection", mock_get_connection):
            from db.tech_signals import save_tech_signals
            infra = InfrastructureSignals(domain="example.com", ns_provider="AWS", mx_provider="Google Workspace", cloud_provider_hints=["AWS"])
            count = await save_tech_signals(1, {}, infra=infra)
        assert count == 3  # ns + mx + cloud hint
        mock_conn.executemany.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_saves_ssl_signals(self, mock_get_connection, mock_conn):
        with patch("db.tech_signals.get_connection", mock_get_connection):
            from db.tech_signals import save_tech_signals
            infra = InfrastructureSignals(domain="example.com", ssl_issuer="Let's Encrypt", ssl_expiry_days=60, ssl_automation_inferred=True)
            count = await save_tech_signals(1, {}, infra=infra)
        assert count == 1
        mock_conn.executemany.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_saves_job_signals(self, mock_get_connection, mock_conn):
        with patch("db.tech_signals.get_connection", mock_get_connection):
            from db.tech_signals import save_tech_signals
            js = JobSignals(tech_mentions=[TechMention(name="Python", category="language", count=3)])
            count = await save_tech_signals(1, {}, job_signals=js)
        assert count == 1

    @pytest.mark.asyncio
    async def test_empty_returns_zero(self, mock_get_connection, mock_conn):
        with patch("db.tech_signals.get_connection", mock_get_connection):
            from db.tech_signals import save_tech_signals
            count = await save_tech_signals(1, {})
        assert count == 0
        mock_conn.executemany.assert_not_awaited()


class TestSavePainInferences:
    @pytest.mark.asyncio
    async def test_saves_inferences(self, mock_get_connection, mock_conn):
        with patch("db.tech_signals.get_connection", mock_get_connection):
            from db.tech_signals import save_pain_inferences
            inferences = [
                PainInference(rule_id="test", title="Test", description="desc", severity="high", evidence=["ev1"], confidence=80),
            ]
            count = await save_pain_inferences(1, inferences)
        assert count == 1
        mock_conn.executemany.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_empty_returns_zero(self, mock_get_connection, mock_conn):
        with patch("db.tech_signals.get_connection", mock_get_connection):
            from db.tech_signals import save_pain_inferences
            count = await save_pain_inferences(1, [])
        assert count == 0
        mock_conn.executemany.assert_not_awaited()


class TestGetSignalsForDomain:
    @pytest.mark.asyncio
    async def test_returns_list(self, mock_get_connection, mock_conn):
        mock_conn.fetch.return_value = [{"id": 1, "tech_name": "React"}]
        with patch("db.tech_signals.get_connection", mock_get_connection):
            from db.tech_signals import get_signals_for_domain
            results = await get_signals_for_domain("example.com")
        assert len(results) == 1
        assert results[0]["tech_name"] == "React"
