# Structured Alert Events

All alert events are emitted as structured JSON log fields via Python's `logging` module with `extra={}`. The JSON formatter (python-json-logger) serializes these automatically in production.

## Event Types

| `event_type` | Meaning | Level | Key Fields |
|---|---|---|---|
| `auth_failure` | 401 from session or API key auth | WARNING | `status_code` |
| `auth_session_error` | Session/DB error during auth lookup | ERROR | — |
| `oauth_callback_error` | OAuth callback missing code, state mismatch, or exchange failure | WARNING/ERROR | `provider`, `user_id` |
| `oauth_integration_connected` | OAuth integration successfully connected | INFO | `provider`, `user_id` |
| `google_sheets_connect` | User initiated Google Sheets OAuth flow | INFO | `user_id` |
| `google_sheets_disconnect` | User disconnected Google Sheets | INFO | `user_id` |
| `google_sheets_import` | Google Sheets import failed | ERROR | `error_code`, `user_id` |
| `google_sheets_push` | Google Sheets push failed | ERROR | `error_code`, `user_id` |
| `integration_provider_error` | Upstream provider (Apollo, etc.) error | ERROR | `provider`, `status_code` |
| `unhandled_5xx` | Unhandled server exception | ERROR | `status_code` |

## Structured Fields

Every alert log entry includes:
- `event_type` — machine-readable event classification
- `status_code` — HTTP status code (where applicable)
- `error_code` — stable error code from exception hierarchy (Google Sheets errors)
- `provider` — OAuth/integration provider name (where applicable)
- `user_id` — authenticated user ID (where applicable)
- `request_id` — injected by RequestIDMiddleware into all log records
- `timestamp`, `level`, `logger` — standard fields from JSON formatter

## Railway Log Trigger Setup

1. Go to Railway Dashboard > Project > Service > Settings > Observability
2. Create a new Log Trigger for each alert:

### Auth Failure Spike (401s)
- **Filter:** `event_type:auth_failure`
- **Threshold:** >15% of requests in 10-minute window
- **Action:** Notify Slack channel
- **Notes:** Spikes may indicate credential stuffing or a broken client integration

### Server Errors (5xx)
- **Filter:** `event_type:unhandled_5xx`
- **Threshold:** >2% of requests in 10-minute window
- **Action:** Notify Slack channel + PagerDuty
- **Notes:** Any sustained 5xx rate requires immediate investigation

### OAuth Failures
- **Filter:** `event_type:oauth_callback_error`
- **Threshold:** >5 occurrences in 10-minute window
- **Action:** Notify Slack channel
- **Notes:** Check if Google/Microsoft OAuth configuration changed. Error codes: `oauth_callback_missing_code`, `oauth_state_invalid`, `oauth_token_exchange_failed`

### Integration Provider Errors
- **Filter:** `event_type:integration_provider_error`
- **Threshold:** >10 occurrences in 10-minute window
- **Action:** Notify Slack channel
- **Notes:** Upstream provider may be degraded — check their status page

### Google Token Revoked
- **Filter:** `error_code:google_token_revoked`
- **Warning threshold:** >5 occurrences in 15-minute window
- **Critical threshold:** >15 occurrences in 15-minute window
- **Action:** Warning → Slack channel; Critical → Slack + PagerDuty
- **Dimensions:** `event_type` (google_sheets_import / google_sheets_push), `error_code`, distinct `user_id` count
- **Notes:** Indicates users' Google access was revoked or refresh tokens expired. A spike across many users may signal an OAuth config change or Google policy enforcement. Individual occurrences are normal — users reconnect via the error message.

### Google Sheets API Errors
- **Filter:** `error_code:google_sheets_api_error`
- **Warning threshold:** >5 occurrences in 15-minute window
- **Critical threshold:** >15 occurrences in 15-minute window
- **Action:** Warning → Slack channel; Critical → Slack + PagerDuty
- **Dimensions:** `event_type` (google_sheets_import / google_sheets_push), `error_code`, distinct `user_id` count
- **Notes:** Catch-all for non-classified Sheets API failures (5xx from Google, unexpected status codes). A spike likely means Google Sheets API is degraded — check https://www.google.com/appsstatus/dashboard/ before escalating.

### Health Check Failures
- **Filter:** `GET /health` returning non-200
- **Threshold:** 3 consecutive failures
- **Action:** Notify Slack + PagerDuty
- **Notes:** Likely database connectivity issue

## False Positive Guidance

- **401 spikes after deploy:** Normal if clients cache stale sessions. Wait 5 minutes before escalating.
- **OAuth failures in dev/staging:** Ignore unless the same pattern appears in production.
- **Single 5xx errors:** Investigate but don't page unless sustained (>2% rate).
- **Integration errors during provider maintenance:** Check Apollo/Google status pages before escalating.
- **Isolated google_token_revoked events:** Normal user behaviour — they revoked access or their token expired. Only investigate if many distinct users are affected simultaneously.
- **google_sheets_api_error spike:** Check Google Workspace Status Dashboard first. If Google is healthy, investigate whether a code change altered request format.
