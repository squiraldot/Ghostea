# Ghostea Phase 3 — Group / Supergroup / Migration Hardening

Phase 3 continues the existing Ghostea architecture. No database schema change is introduced.

## Scope
- Basic Group and Supergroup lifecycle compatibility.
- Group -> Supergroup migration state preservation.
- Journaled/resumable migration remains the durable recovery boundary.
- Telegram remains authoritative for the post-migration chat type/forum state.
- Large Telegram chat IDs are handled as Python integers and PostgreSQL `bigint` values.
- Target-state collisions fail closed; existing target data is never overwritten.
- Invalid/same/zero migration identifiers are rejected before state mutation.

## Testing / Deployment
- `database.sql`: **DO NOT rerun** for this phase; schema is unchanged.
- Render: **YES, redeploy** after merging this phase because Python source changed.
- Vercel: **NO**, unless dashboard source independently changed.
- UptimeRobot: **NO configuration change**; keep the existing 5-minute health check.
- Telegram: after Render redeploy, perform a real migration test only in a disposable/test group first.
