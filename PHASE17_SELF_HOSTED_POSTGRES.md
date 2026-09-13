# Phase 17 — Self-Hosted PostgreSQL Provider

## Goal

Enable the self-hosted deployment profile to use a normal PostgreSQL server on
the VPS while keeping the existing Managed profile (Render + Supabase) intact.

## Configuration

```env
GHOSTEA_DEPLOYMENT_MODE=self_hosted
GHOSTEA_DATABASE_PROVIDER=postgresql
GHOSTEA_STORAGE_PROVIDER=local
GHOSTEA_DASHBOARD_HOST=vps
DATABASE_URL=postgresql://ghostea:CHANGE_ME@127.0.0.1:5432/ghostea
```

`DATABASE_URL` is only required for the PostgreSQL provider. Managed mode still
uses `SUPABASE_URL` and `SUPABASE_KEY`.

## Schema

The existing `database.sql` is PostgreSQL-compatible and remains the canonical
Ghostea schema. For a fresh VPS database:

```bash
export DATABASE_URL='postgresql://ghostea:...@127.0.0.1:5432/ghostea'
./deploy/selfhost/init-db.sh
```

No separate or divergent VPS schema is introduced.

## Compatibility

The PostgreSQL adapter implements the same database contract as the
Supabase/PostgREST adapter. Existing storage and business services therefore
do not need provider-specific branches.

Supported query features used by Ghostea include:

- equality/inequality filters
- range filters
- `in` / `not.in`
- boolean/null filters
- ordering
- bounded limits/offsets
- insert/update/delete
- primary/unique-key upsert
- exact counts
- required-table probes

## Deployment

For Docker self-hosting, `docker-compose.selfhost.yml` now includes:

- PostgreSQL 16
- persistent PostgreSQL volume
- PostgreSQL health check
- Ghostea dependency on a healthy database
- a private Docker-network database connection
- the existing persistent Ghostea data volume

The PostgreSQL port is not published by the compose file.

## Safety

- PostgreSQL URLs and passwords must never be committed.
- Self-hosted mode fails closed unless a valid PostgreSQL `DATABASE_URL` is set.
- It never silently falls back to Supabase.
- Managed mode remains unchanged.
