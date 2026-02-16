# Soak Checklist

After every production deploy, work through this checklist at the specified intervals.

## T+0 (Immediately after deploy)

- [ ] `make smoke-prod APP_URL=<production-url>` passes
- [ ] `GET /health` returns `{"status": "ok", "db": "ok"}`
- [ ] No `event_type:unhandled_5xx` in structured logs
- [ ] Deploy completed without errors in Railway dashboard

## T+15 minutes

- [ ] No alert triggers fired (check Slack channel)
- [ ] Spot-check: log in via Google OAuth, load dashboard
- [ ] `auth_failure` rate is at normal baseline (not spiking)
- [ ] No new error patterns in structured logs

## T+1 hour

- [ ] Request latency is at normal baseline (no slow-request warnings)
- [ ] Memory usage is stable (no upward trend in Railway metrics)
- [ ] If migration was included: verify new schema is correct (`\d table_name`)
- [ ] Worker is processing jobs (check task queue for stuck/failed tasks)

## T+4 hours

- [ ] Background worker queue depth is at normal levels
- [ ] No user-reported issues in support channels
- [ ] Credit deduction is functioning correctly (spot-check a recent job)
- [ ] Integration provider endpoints responding normally

## T+24 hours

- [ ] Compare key metrics to pre-deploy baseline:
  - Request volume
  - Error rate
  - p50/p95 latency
  - Worker throughput
- [ ] No lingering alerts or anomalies
- [ ] Mark release as **stable** in release template
- [ ] Close release template with notes on any issues encountered
