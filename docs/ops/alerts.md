# Structured Alert Events

All alert events are emitted as structured JSON log fields via Python's `logging` module with `extra={}`. The JSON formatter (python-json-logger) serializes these automatically in production.

## Event Types

| `event_type` | Meaning | Level | Key Fields |
|---|---|---|---|
| `auth_failure` | 401 from session or API key auth | WARNING | `status_code` |
| `auth_session_error` | Session/DB error during auth lookup | ERROR | — |
| `oauth_callback_failure` | Google/Microsoft OAuth callback error | ERROR | `provider`, `status_code` |
| `integration_provider_error` | Upstream provider (Apollo, etc.) error | ERROR | `provider`, `status_code` |
| `unhandled_5xx` | Unhandled server exception | ERROR | `status_code` |

## Structured Fields

Every alert log entry includes:
- `event_type` — machine-readable event classification
- `status_code` — HTTP status code (where applicable)
- `provider` — OAuth/integration provider name (where applicable)
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
- **Filter:** `event_type:oauth_callback_failure`
- **Threshold:** >5 occurrences in 10-minute window
- **Action:** Notify Slack channel
- **Notes:** Check if Google/Microsoft OAuth configuration changed

### Integration Provider Errors
- **Filter:** `event_type:integration_provider_error`
- **Threshold:** >10 occurrences in 10-minute window
- **Action:** Notify Slack channel
- **Notes:** Upstream provider may be degraded — check their status page

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
