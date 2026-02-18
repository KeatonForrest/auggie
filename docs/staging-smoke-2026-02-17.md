# Staging Smoke Run — 2026-02-17

Google Sheets reliability hardening + LinkedIn messaging visibility.

## Messaging

| # | Step | Expected | Pass |
|---|------|----------|------|
| 1 | Open any research document | Only **Email Sequence** and **LinkedIn DM** tabs visible (no Connection Request tab) | [ ] |
| 2 | Generate LinkedIn DM **with** screenshot | 200, message returned, content_type matches screenshot | [ ] |
| 3 | Generate LinkedIn DM **without** screenshot | 200, message returned, content_type = "none" | [ ] |
| 4 | `POST /document/{id}/linkedin-message` with `mode=connection_request` | 422, `error.code = "connection_note_disabled"` | [ ] |

## Google Sheets — Connect & Import

| # | Step | Expected | Pass |
|---|------|----------|------|
| 5 | Integrations page → Connect Google Sheets | Redirects to Google consent, returns to /integrations with green status | [ ] |
| 6 | Import a valid Google Sheets URL | 200, list created, rows imported correctly | [ ] |
| 7 | Import an invalid URL (not a Sheets link) | 400, `error.code = "invalid_spreadsheet_url"` | [ ] |
| 8 | Import a sheet the user cannot access | 403, `error.code = "sheet_access_denied"` | [ ] |
| 9 | Import a non-existent spreadsheet ID | 404, `error.code = "sheet_not_found"` | [ ] |

## Google Sheets — Push

| # | Step | Expected | Pass |
|---|------|----------|------|
| 10 | Push list to new Google Sheet | 200, `spreadsheet_url` returned, sheet contains data | [ ] |
| 11 | Push without Google connected | 400, `error.code = "google_integration_missing"` | [ ] |

## Google Sheets — Revoke & Recover

| # | Step | Expected | Pass |
|---|------|----------|------|
| 12 | Revoke app access at https://myaccount.google.com/permissions | Token revoked in Google console | [ ] |
| 13 | Retry import after revocation | 401, `error.code = "google_token_revoked"` — message says reconnect | [ ] |
| 14 | Retry push after revocation | 401, `error.code = "google_token_revoked"` — message says reconnect | [ ] |
| 15 | Reconnect Google Sheets | OAuth flow completes, integration green again | [ ] |
| 16 | Re-run import after reconnect | 200, rows imported successfully | [ ] |
| 17 | Re-run push after reconnect | 200, sheet created successfully | [ ] |

## Summary

- Total checks: 17
- Passed: __ / 17
- Blocked / failed: (list any here)

## Notes

(capture any issues, latency observations, or unexpected behaviour)
