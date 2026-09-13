# Phase 22 — Managed Deployment Profile

Ghostea's managed baseline is now an explicit supported topology:

- Bot/API: Render
- Database: Supabase PostgreSQL through the existing REST provider
- Storage: Supabase Storage
- Dashboard: Vercel

The self-hosted profile remains first-class and is unchanged.

## Managed environment

Backend/Render:
- BOT_TOKEN
- SUPABASE_URL
- SUPABASE_KEY
- DASHBOARD_API_KEY
- DASHBOARD_ORIGIN
- GHOSTEA_PROXY_SIGNING_SECRET
- GHOSTEA_DEPLOYMENT_MODE=managed
- GHOSTEA_DATABASE_PROVIDER=supabase_rest
- GHOSTEA_STORAGE_PROVIDER=supabase
- GHOSTEA_DASHBOARD_HOST=vercel
- GHOSTEA_SUPABASE_STORAGE_BUCKET=ghostea

Vercel:
- GHOSTEA_API_URL
- GHOSTEA_API_KEY
- GHOSTEA_ADMIN_PASSWORD
- GHOSTEA_SESSION_SECRET
- GHOSTEA_PROXY_SIGNING_SECRET

Provider combinations such as PostgreSQL+local+VPS are intentionally reserved for the self-hosted profile; custom combinations are deferred to Phase 24.

No database migration is required.
