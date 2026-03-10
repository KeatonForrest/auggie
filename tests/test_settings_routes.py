"""Tests for onboarding/settings routes."""

import pytest
from unittest.mock import AsyncMock, patch


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
