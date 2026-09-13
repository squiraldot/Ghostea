# Phase 32 — Monitoring, Alerting & Operational Dashboard

- Added provider-neutral `/api/operations` diagnostics for authenticated operators.
- Added derived critical/warning alerts for database health, readiness, dead jobs, stale jobs, stopped workers and recent operational errors.
- Added public `/health/ready` readiness endpoint for deeper uptime monitoring while keeping `/health` as liveness.
- Added bounded operational dashboard with queue, database, schema, cache, deployment and recent event views.
- Added configurable alert thresholds without a database migration.
- Fixed the custom + VPS dashboard-host combination so custom VPS deployments serve the dashboard locally.
- Fixed `/api/health` schema version reporting to read the actual `ghostea_schema_meta` value instead of a stale hard-coded version.
