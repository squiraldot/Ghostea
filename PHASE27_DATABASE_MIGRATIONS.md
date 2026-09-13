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
python scripts/ghostea_migrate.py --apply-psql  # Android/Termux with psql
python scripts/ghostea_migrate.py --apply
```

`--apply` is intentionally PostgreSQL-only. The tool fails closed for a
REST-only provider instead of pretending DDL was executed.

## Current version

The canonical schema is version **11**. Existing Phase 26 databases normally
report version 9 and have migration 10 pending. Fresh databases created from
the current `database.sql` are already at version 10.

## Safety

- No destructive migrations are included.
- Migration files are checksummed.
- Checksum drift blocks readiness.
- Do not edit an already-applied migration; create the next numbered migration.
- Always back up before applying production migrations.


## Android / Termux migration

For Managed Supabase testing on Android, the migration CLI supports the local PostgreSQL `psql` client and does not require the Python `psycopg` package or Supabase credentials for the direct PostgreSQL execution path. Set `DATABASE_URL` to the Supabase PostgreSQL connection string and run:

```text
python scripts/ghostea_migrate.py --status
python scripts/ghostea_migrate.py --apply-psql
python scripts/ghostea_migrate.py --status
```

The psql path reads the current schema version directly from PostgreSQL and applies only pending migrations. Existing Phase 26 databases at version 9 are expected to apply migrations 10 and 11 in order.
