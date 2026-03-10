"""Tests for onboarding/settings routes."""

import pytest
from unittest.mock import AsyncMock, patch

from main import app
import routes.settings as settings_routes


@pytest.mark.asyncio
async def test_onboarding_enqueues_seller_profile_enrichment(authed_client):
    with patch("routes.settings.update_user_profile", new_callable=AsyncMock) as mock_update, \
         patch("routes.settings.clear_seller_profile", new_callable=AsyncMock) as mock_clear, \
         patch("routes.settings.create_tracked_task", new_callable=AsyncMock) as mock_task:

        response = await authed_client.post(
            "/onboarding",
            data={
                "company_website": "acme.com",
                "target_personas_text": "VP Sales",
            },
            follow_redirects=False,
        )

        assert response.status_code == 302
        kwargs = mock_update.await_args.kwargs
        assert kwargs["company_website"] == "https://acme.com"
        assert kwargs["company_name"] == "Acme"
        assert kwargs["target_personas"] == "VP Sales"
        mock_clear.assert_awaited_once_with(1)
        mock_task.assert_awaited_once()


@pytest.mark.asyncio
async def test_onboarding_page_uses_website_signals_and_icp_only(async_client):
    async def _fake_user():
        return {
            "id": 1,
            "email": "test@test.com",
            "name": "Test User",
            "product_context": "",
        }

    app.dependency_overrides[settings_routes.require_auth] = _fake_user
    try:
        response = await async_client.get("/onboarding")
    finally:
        app.dependency_overrides.pop(settings_routes.require_auth, None)

    assert response.status_code == 200
    body = response.text
    assert "Company Website" in body
    assert "Custom Signals" in body
    assert "Who are you going after?" in body
    assert "What You Sell" not in body
    assert "What problems does your product/service solve?" not in body


@pytest.mark.asyncio
async def test_settings_page_frames_manual_fields_as_overrides(async_client):
    async def _fake_user():
        return {
            "id": 1,
            "email": "test@test.com",
            "name": "Test User",
            "product_context": "Existing seller context",
            "company_website": "https://acme.com",
            "company_name": "Acme",
            "seller_product_category": "",
            "problems_solved": "",
            "target_company_size": "",
            "target_industries": "",
            "target_personas": "VP Sales",
            "product_type": "saas",
            "custom_signals": "",
        }

    app.dependency_overrides[settings_routes.require_onboarding] = _fake_user
    try:
        response = await async_client.get("/settings")
    finally:
        app.dependency_overrides.pop(settings_routes.require_onboarding, None)

    assert response.status_code == 200
    body = response.text
    assert "Seller Profile Overrides" in body
    assert "What You Sell" not in body
    assert "What problems does your product/service solve?" in body
