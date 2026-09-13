# Phase 20 — Database Provider System

Ghostea now treats database access as a deployment-neutral provider contract.
Managed deployments can use Supabase/PostgREST, while self-hosted deployments
use direct PostgreSQL. Business/storage services keep the same repository API.

## Supported providers

- `supabase_rest` — managed Supabase/PostgREST
- `postgresql` — direct PostgreSQL for VPS/self-hosted

## Compatibility guarantees

Both providers expose the same operations: select, insert, upsert, update,
delete, count, table checks, and close. PostgreSQL result values are normalized
to the JSON-compatible shapes produced by PostgREST (timestamps, UUIDs,
numerics, nested JSON).

Provider selection is fail-closed. A selected provider does not silently fall
back to another database backend.

## Configuration

Managed:

```env
GHOSTEA_DEPLOYMENT_MODE=managed
GHOSTEA_DATABASE_PROVIDER=supabase_rest
SUPABASE_URL=https://...
SUPABASE_KEY=...
```

Self-hosted:

```env
GHOSTEA_DEPLOYMENT_MODE=self_hosted
GHOSTEA_DATABASE_PROVIDER=postgresql
DATABASE_URL=postgresql://...
```

## Database ownership

The canonical `database.sql` remains the schema source for both providers.
Phase 20 adds no schema changes.

## Operational notes

- PostgreSQL connections are lazy and scoped to worker threads.
- PostgreSQL uses parameterized values and an allowlisted Ghostea table set.
- HTTP/PostgREST remains dependency-free through `urllib`.
- No Supabase service key is required in self-hosted PostgreSQL mode.
- Do not expose PostgreSQL's TCP port publicly unless there is a deliberate,
  separately secured reason to do so.
