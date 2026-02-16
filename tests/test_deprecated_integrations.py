"""Tests verifying deprecated integrations return 410, disconnect handlers still work, and kept integrations do not return 410."""

import pytest
from unittest.mock import AsyncMock, patch
from starlette.responses import JSONResponse, RedirectResponse


# =============================================================================
# Deprecated integration routes → 410
# =============================================================================

DEPRECATED_ROUTES = [
    # HubSpot
    ("get", "/integrations/hubspot/connect"),
    ("get", "/integrations/hubspot/callback"),
    ("get", "/integrations/hubspot/companies"),
    ("post", "/integrations/hubspot/import"),
    # Instantly
    ("post", "/integrations/instantly/connect"),
    ("get", "/integrations/instantly/campaigns"),
    # Smartlead
    ("post", "/integrations/smartlead/connect"),
    ("get", "/integrations/smartlead/campaigns"),
    # Salesforce
    ("get", "/integrations/salesforce/connect"),
    ("get", "/integrations/salesforce/callback"),
    ("get", "/integrations/salesforce/accounts"),
    ("post", "/integrations/salesforce/import"),
    # Outreach
    ("get", "/integrations/outreach/connect"),
    ("get", "/integrations/outreach/callback"),
    ("get", "/integrations/outreach/sequences"),
    # SalesLoft
    ("get", "/integrations/salesloft/connect"),
    ("get", "/integrations/salesloft/callback"),
    ("get", "/integrations/salesloft/cadences"),
    # Gong Engage
    ("get", "/integrations/gong_engage/connect"),
    ("get", "/integrations/gong_engage/callback"),
    ("get", "/integrations/gong_engage/flows"),
    # ZoomInfo
    ("get", "/integrations/zoominfo/connect"),
    ("get", "/integrations/zoominfo/callback"),
    ("get", "/integrations/zoominfo/companies"),
    ("post", "/integrations/zoominfo/import"),
    # PDL
    ("post", "/integrations/pdl/connect"),
    ("post", "/integrations/pdl/search"),
    ("post", "/integrations/pdl/import"),
    # Lusha
    ("post", "/integrations/lusha/connect"),
    ("post", "/integrations/lusha/import"),
    # Cognism
    ("post", "/integrations/cognism/connect"),
    ("post", "/integrations/cognism/import"),
]

DEPRECATED_PUSH_ROUTES = [
    ("post", "/lists/1/push-instantly"),
    ("post", "/lists/1/push-smartlead"),
    ("post", "/lists/1/push-instantly-campaign"),
    ("post", "/lists/1/push-smartlead-campaign"),
    ("post", "/lists/1/push-outreach"),
    ("post", "/lists/1/push-salesloft"),
    ("post", "/lists/1/push-gong-engage"),
]


class TestDeprecatedIntegrationRoutes:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("method,path", DEPRECATED_ROUTES, ids=[f"{m.upper()} {p}" for m, p in DEPRECATED_ROUTES])
    async def test_returns_410(self, authed_client, method, path):
        fn = getattr(authed_client, method)
        response = await fn(path, follow_redirects=False)
        assert response.status_code == 410, f"Expected 410 for {method.upper()} {path}, got {response.status_code}"
        body = response.json()
        assert body["error"]["code"] == "provider_deprecated"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("method,path", DEPRECATED_PUSH_ROUTES, ids=[f"{m.upper()} {p}" for m, p in DEPRECATED_PUSH_ROUTES])
    async def test_push_returns_410(self, authed_client, method, path):
        fn = getattr(authed_client, method)
        response = await fn(path, json={}, follow_redirects=False)
        assert response.status_code == 410, f"Expected 410 for {method.upper()} {path}, got {response.status_code}"
        body = response.json()
        assert body["error"]["code"] == "provider_deprecated"


# =============================================================================
# Disconnect handlers still work → 303 redirect
# =============================================================================

DISCONNECT_ROUTES = [
    ("post", "/integrations/hubspot/disconnect"),
    ("post", "/integrations/instantly/disconnect"),
    ("post", "/integrations/smartlead/disconnect"),
    ("post", "/integrations/salesforce/disconnect"),
    ("post", "/integrations/outreach/disconnect"),
    ("post", "/integrations/salesloft/disconnect"),
    ("post", "/integrations/gong_engage/disconnect"),
    ("post", "/integrations/zoominfo/disconnect"),
    ("post", "/integrations/pdl/disconnect"),
    ("post", "/integrations/lusha/disconnect"),
    ("post", "/integrations/cognism/disconnect"),
]


class TestDisconnectStillWorks:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("method,path", DISCONNECT_ROUTES, ids=[f"{m.upper()} {p}" for m, p in DISCONNECT_ROUTES])
    async def test_disconnect_returns_303(self, authed_client, method, path):
        """Disconnect handlers should call delete_integration and redirect."""
        with patch("routes.integrations.delete_integration", new_callable=AsyncMock, return_value=True) as mock_delete:
            fn = getattr(authed_client, method)
            response = await fn(path, follow_redirects=False)
        assert response.status_code == 303, f"Expected 303 for {method.upper()} {path}, got {response.status_code}"
        assert response.headers.get("location") == "/integrations"
        mock_delete.assert_called_once()


class TestV1PushDeprecated:
    @pytest.mark.asyncio
    async def test_api_push_returns_410(self):
        """V1 API push endpoint returns 410 for deprecated Instantly push."""
        from main import app
        from api.auth import require_api_key
        from httpx import AsyncClient, ASGITransport

        fake_api_user = {
            "id": 1,
            "api_key_id": 99,
            "email": "test@test.com",
            "company_name": "Test Co",
        }

        app.dependency_overrides[require_api_key] = lambda: fake_api_user
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/v1/lists/1/push",
                    json={"campaign_id": "camp-1"},
                    headers={"Authorization": "Bearer test-key"},
                )
        finally:
            app.dependency_overrides.pop(require_api_key, None)

        assert response.status_code == 410
        body = response.json()
        assert body["error"]["code"] == "provider_deprecated"


# =============================================================================
# Kept integration routes → NOT 410
# =============================================================================

KEPT_ROUTES = [
    # Apollo (connect needs JSON body)
    ("post", "/integrations/apollo/connect", {"api_key": "test-key"}),
    ("post", "/integrations/apollo/disconnect", None),
    # Slack (connect needs JSON body)
    ("post", "/integrations/slack/connect", {"webhook_url": "https://hooks.slack.com/test"}),
    ("post", "/integrations/slack/disconnect", None),
    # Teams (connect needs JSON body)
    ("post", "/integrations/teams/connect", {"webhook_url": "https://outlook.webhook.office.com/test"}),
    ("post", "/integrations/teams/disconnect", None),
    # Google Sheets
    ("get", "/integrations/google_sheets/connect", None),
    ("post", "/integrations/google_sheets/disconnect", None),
]


class TestKeptRoutesDontReturn410:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "method,path,body",
        KEPT_ROUTES,
        ids=[f"{m.upper()} {p}" for m, p, _ in KEPT_ROUTES],
    )
    async def test_not_410(self, authed_client, method, path, body):
        """Kept integration routes should NOT return 410."""
        fn = getattr(authed_client, method)
        kwargs = {"follow_redirects": False}
        if body:
            kwargs["json"] = body
        with patch("routes.integrations.get_integration", new_callable=AsyncMock, return_value=None), \
             patch("routes.integrations.upsert_integration", new_callable=AsyncMock), \
             patch("routes.integrations.delete_integration", new_callable=AsyncMock, return_value=True), \
             patch("routes.integrations._apikey_connect", new_callable=AsyncMock, return_value=JSONResponse({"success": True})), \
             patch("routes.integrations._oauth_connect", new_callable=AsyncMock, return_value=RedirectResponse(url="/integrations", status_code=302)), \
             patch("routes.integrations.validate_webhook_url", new_callable=AsyncMock, return_value=True), \
             patch("routes.integrations.validate_teams_webhook_url", new_callable=AsyncMock, return_value=True):
            response = await fn(path, **kwargs)
        assert response.status_code != 410, f"Kept route {method.upper()} {path} should not return 410"


# =============================================================================
# Automation deprecation
# =============================================================================

class TestDeprecatedDisconnectUX:
    """Verify the Deprecated Integrations section on /integrations page."""

    @pytest.mark.asyncio
    async def test_shows_section_when_deprecated_provider_connected(self, authed_client):
        """When a deprecated provider is connected, the page should show the disconnect section."""
        with patch("routes.integrations.get_user_integrations", new_callable=AsyncMock, return_value=[
            {"provider": "hubspot", "access_token": "tok"},
        ]), patch("routes.integrations.get_user_usage", new_callable=AsyncMock, return_value={
            "bonus_credits": 0, "is_admin": False,
        }):
            response = await authed_client.get("/integrations")
        assert response.status_code == 200
        html = response.text
        assert "Deprecated Integrations" in html
        assert "HubSpot" in html
        assert '/integrations/hubspot/disconnect' in html

    @pytest.mark.asyncio
    async def test_hides_section_when_no_deprecated_providers(self, authed_client):
        """When only supported providers are connected, no deprecated section should appear."""
        with patch("routes.integrations.get_user_integrations", new_callable=AsyncMock, return_value=[
            {"provider": "apollo", "access_token": "tok"},
        ]), patch("routes.integrations.get_user_usage", new_callable=AsyncMock, return_value={
            "bonus_credits": 0, "is_admin": False,
        }):
            response = await authed_client.get("/integrations")
        assert response.status_code == 200
        assert "Deprecated Integrations" not in response.text


class TestDeprecatedAutomationActions:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("action,label", [
        ("push_instantly", "Instantly"),
        ("push_smartlead", "Smartlead"),
        ("push_outreach", "Outreach"),
        ("push_salesloft", "SalesLoft"),
    ])
    async def test_deprecated_action_fails(self, action, label):
        from services.automation import execute_action

        rule = {"id": 1, "name": "test", "action": action, "action_config": {}}
        accounts = [{"id": 1, "status": "completed"}]

        with patch("services.automation.create_automation_run", new_callable=AsyncMock, return_value={"id": 1}), \
             patch("services.automation.complete_automation_run", new_callable=AsyncMock) as mock_complete:
            await execute_action(rule, user_id=1, list_id=1, accounts=accounts)

        mock_complete.assert_called_once()
        call_args = mock_complete.call_args[0]
        assert call_args[1] == "failed"
        assert "deprecated" in call_args[2].lower()
