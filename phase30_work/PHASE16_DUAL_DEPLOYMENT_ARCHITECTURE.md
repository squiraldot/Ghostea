# Phase 16 — Dual Deployment Architecture

## Objective
Keep one Ghostea codebase while supporting two explicit deployment profiles:

- **managed**: current Render + Supabase + Vercel architecture
- **self_hosted**: target VPS-only architecture

Phase 16 establishes configuration and provider boundaries. Concrete
PostgreSQL, local-storage and VPS-dashboard implementations arrive in later
phases.

## Managed (current)
```env
GHOSTEA_DEPLOYMENT_MODE=managed
GHOSTEA_DATABASE_PROVIDER=supabase_rest
GHOSTEA_STORAGE_PROVIDER=supabase
GHOSTEA_DASHBOARD_HOST=vercel
```

This is the default and preserves the existing deployment.

## Self-hosted target
```env
GHOSTEA_DEPLOYMENT_MODE=self_hosted
GHOSTEA_DATABASE_PROVIDER=postgresql
GHOSTEA_STORAGE_PROVIDER=local
GHOSTEA_DASHBOARD_HOST=vps
```

Phase 16 validates this profile but fails closed at runtime for PostgreSQL
until Phase 17 implements it. This prevents a VPS deployment from silently
falling back to Supabase.

## Architecture rule
Business services depend on provider contracts rather than Render, Supabase,
Vercel, Docker or systemd. Provider selection is centralized.

## No migration
No database SQL migration is required in Phase 16. Existing managed users can
continue on Render + Supabase + Vercel without configuration changes.
