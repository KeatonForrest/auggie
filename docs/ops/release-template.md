# Release Template

Copy this template for each production deploy.

---

## Release: [DATE]

**SHA:** `[commit hash]`
**PR:** #[number] — [title]
**Deploy owner:** [name]
**Rollback owner:** [name]

### Migration Details

- [ ] This release includes database migrations
- Migration file(s): `[path or N/A]`
- Migration type: [additive / destructive / data / N/A]
- Rollback strategy: [describe or "no migration"]

### Go / No-Go Checklist

- [ ] CI green on merge commit
- [ ] No open P0/P1 issues
- [ ] Migration reviewed (if applicable)
- [ ] Rollback owner confirmed available
- [ ] Release template filled out (this document)

### Post-Deploy Checks

- [ ] `GET /health` → 200
- [ ] `make smoke-prod` passes
- [ ] OAuth login works (spot-check)
- [ ] Structured logs clean (no unexpected `event_type` spikes)
- [ ] Soak checklist started (see `soak-checklist.md`)

### Rollback Decision

- [ ] Rollback triggered? **Yes / No**
- Reason: [if yes, describe]
- Time of rollback: [UTC]
- Rolled back to: [SHA]

### Notes

[Any additional context, known issues, or follow-up items]
