# Database Migrations

## Pre-Migration Checklist

- [ ] Migration SQL reviewed by at least one other engineer
- [ ] Migration tested against a copy of production schema
- [ ] Expand/contract pattern used (no destructive changes in the same deploy as code changes)
- [ ] Rollback plan documented in release template
- [ ] Backup verified (Railway automatic backups or manual `pg_dump`)

## Expand/Contract Pattern

Always separate schema changes from code changes to enable safe rollbacks.

### Example: Adding a column

**Phase 1 — Expand (deploy A):**
```sql
ALTER TABLE accounts ADD COLUMN priority_score INTEGER;
```
- Old code continues working (ignores the new column)
- New column is nullable, no default required yet
- Deploy this migration alone, verify it succeeds

**Phase 2 — Migrate code (deploy B):**
- Update application code to read/write the new column
- Backfill existing rows if needed:
```sql
UPDATE accounts SET priority_score = 50 WHERE priority_score IS NULL;
```

**Phase 3 — Contract (deploy C, optional):**
- Add NOT NULL constraint if desired:
```sql
ALTER TABLE accounts ALTER COLUMN priority_score SET NOT NULL;
```
- This is safe because all rows were backfilled in Phase 2

### Why this works
- If deploy B fails, rollback to deploy A — the column exists but is unused, no data loss
- If deploy C fails, rollback to deploy B — the column is still nullable, code still works

## Running Migrations

Migrations are run via direct `psql` connection to the Railway PostgreSQL instance:

```bash
# Get connection string from Railway dashboard or CLI
railway connect postgres

# Or use psql directly
psql "$DATABASE_URL" -f migrations/XXXX_description.sql
```

## Dangerous Operations

These operations require extra caution and should never be done in the same deploy as code changes:

| Operation | Risk | Mitigation |
|---|---|---|
| `ALTER TABLE ... ADD COLUMN ... NOT NULL` (without default) | Fails if table has existing rows | Add column as nullable first, backfill, then add constraint |
| `CREATE INDEX` on large table | Locks table for duration | Use `CREATE INDEX CONCURRENTLY` |
| `ALTER TABLE ... ALTER COLUMN ... TYPE` | Rewrites entire table, locks it | Create new column, migrate data, swap in code, drop old column |
| `DROP COLUMN` | Irreversible data loss | Only drop after code no longer references it (contract phase) |
| `DROP TABLE` | Irreversible data loss | Rename to `_deprecated_` first, drop after verification period |
| `TRUNCATE` / `DELETE` without WHERE | Data loss | Always have a backup, always use WHERE clause |
