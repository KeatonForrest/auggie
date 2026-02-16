# Changelog

## 2026-02-16 — Integration Deprecation (Phase 1)

Deprecated providers — HubSpot, Salesforce, Outreach, SalesLoft, Gong Engage, ZoomInfo, Instantly, Smartlead, People Data Labs, Lusha, and Cognism — now return `410 Gone` on all routes except disconnect. Existing connections can still be disconnected from **Settings > Integrations**, where a new "Deprecated Integrations" section surfaces any legacy tokens. Supported integrations going forward are Apollo, Google Sheets, Slack, and Microsoft Teams. On the API side, `POST /v1/lists/{list_id}/push` returns 410 with `{"error": {"code": "provider_deprecated", ...}}`.
