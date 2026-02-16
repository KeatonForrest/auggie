# Rollback Runbook

## When to Rollback

Rollback immediately if:
- Health endpoint returns non-200 for >1 minute post-deploy
- 5xx error rate exceeds 5% for >2 minutes
- OAuth login is completely broken for all users
- Data corruption or incorrect writes detected

## Railway Rollback Steps

1. Open Railway Dashboard
2. Navigate to the project > service
3. Click **Deployments** tab
4. Find the previous green (successful) deployment
5. Click the **three-dot menu** (⋯) on that deployment
6. Select **Rollback**
7. Confirm the rollback

Railway will redeploy the previous image. This typically takes 30-60 seconds.

## Post-Rollback Verification

Run these checks immediately after the rollback completes:

1. **Health check:** `curl https://<app-url>/health` returns `{"status": "ok", "db": "ok"}`
2. **Smoke tests:** `make smoke-prod APP_URL=https://<app-url>`
3. **OAuth login:** Manually test Google sign-in flow end-to-end
4. **Structured logs:** Check Railway logs for any new `event_type:unhandled_5xx` entries
5. **Worker:** Verify background jobs are processing (check task queue for stuck tasks)

## Database Migration Caveats

If the failed deploy included a database migration:

- **Additive migrations (new columns, new tables):** Safe to rollback. The old code simply ignores the new columns/tables. Clean up the unused schema later.
- **Destructive migrations (dropped columns, type changes):** The rollback will NOT undo the migration. The old code may fail if it depends on removed columns. You must manually restore the schema or apply a compensating migration.
- **Data migrations (backfills, transforms):** Assess on a case-by-case basis. If data was transformed in a lossy way, you may need to restore from backup.

Always use the expand/contract pattern (see `migrations.md`) to avoid this scenario.

## Communication Template

Post in the team Slack channel:

```
🔄 Production rollback performed

- **Time:** [UTC timestamp]
- **Rolled back from:** [SHA / PR #]
- **Rolled back to:** [previous deployment SHA]
- **Reason:** [brief description]
- **Impact:** [user-facing impact, if any]
- **Status:** [investigating / resolved]
- **Next steps:** [what we're doing to fix the root cause]
```
