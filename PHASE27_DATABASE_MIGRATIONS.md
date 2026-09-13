# Phase 27 — Advanced Database Migrations & Versioning

Ghostea now uses an ordered, checksummed migration catalog for incremental
database upgrades.

## Migration model

- `ghostea/migrations/*.sql` contains numbered migrations.
- `ghostea_schema_migrations` records applied version, name, checksum and time.
- `ghostea_schema_meta.schema_version` remains the fast current-version marker.
- Migration checks detect checksum drift and versions newer than the shipped catalog.
- PostgreSQL application runs each migration in a transaction and takes a
  transaction-scoped advisory lock to prevent concurrent migration runners.
- The migration SQL is additive and safe to review before execution.
- Supabase/PostgREST has no DDL endpoint in the provider contract, so managed
  deployments should use `--sql` to generate the exact SQL and execute it in
  the Supabase SQL Editor.

## Commands

```text
python scripts/ghostea_migrate.py --status
python scripts/ghostea_migrate.py --plan
python scripts/ghostea_migrate.py --sql > phase27_migrations.sql
python scripts/ghostea_migrate.py --dry-run
python scripts/ghostea_migrate.py --apply
```

`--apply` is intentionally PostgreSQL-only. The tool fails closed for a
REST-only provider instead of pretending DDL was executed.

## Current version

The canonical schema is version **10**. Existing Phase 26 databases normally
report version 9 and have migration 10 pending. Fresh databases created from
the current `database.sql` are already at version 10.

## Safety

- No destructive migrations are included.
- Migration files are checksummed.
- Checksum drift blocks readiness.
- Do not edit an already-applied migration; create the next numbered migration.
- Always back up before applying production migrations.
