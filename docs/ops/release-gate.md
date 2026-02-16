# Release Gate

Every production deploy must pass this gate. No exceptions.

## Pre-Deploy Checklist

- [ ] CI is green on the merge commit (`.github/workflows/ci.yml`)
- [ ] No open P0 or P1 issues tagged for this release
- [ ] Database migrations reviewed (see `migrations.md`)
- [ ] Release template filled out (see `release-template.md`)
- [ ] Rollback owner identified and available

## Deploy Sequence

1. Fill out release template with SHA, PR link, migration details
2. Verify CI passed on the exact commit being deployed
3. Deploy via Railway (push to `main` or manual deploy)
4. Run smoke tests: `make smoke-prod APP_URL=<production-url>`
5. Begin soak period (see `soak-checklist.md`)

## Post-Deploy Verification

1. `GET /health` returns `{"status": "ok", "db": "ok"}`
2. Smoke script passes all checks
3. Spot-check OAuth login (Google + Microsoft if configured)
4. Review structured logs for unexpected `event_type` entries

## Rollback Criteria

Trigger an immediate rollback if:
- Health endpoint returns non-200 for >1 minute
- 5xx error rate exceeds 5% for >2 minutes
- OAuth login is completely broken
- Data corruption is detected

See `rollback-runbook.md` for rollback procedure.

## Never-Skip Policy

- **"It's a small change"** — small changes cause outages too. Run the gate.
- **"CI is slow"** — wait for it. Deploy without CI only if production is currently down and this is the fix.
- **"No migrations"** — still fill out the release template. The checklist catches non-DB issues too.
