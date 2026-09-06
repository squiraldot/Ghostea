# Deployment Configuration Audit — H15

## Environment variables

### Render
Required:
- `BOT_TOKEN`
- `SUPABASE_URL`
- `SUPABASE_KEY`
- `DASHBOARD_API_KEY`
- `DASHBOARD_ORIGIN`
- `GHOSTEA_ADMIN_PASSWORD`

Optional:
- `GHOSTEA_SUPERADMIN_USERNAME` (defaults to `superadmin`)

Automatic:
- `PORT` (Render supplies this)

### Vercel
Required:
- `GHOSTEA_API_URL`
- `GHOSTEA_API_KEY`
- `GHOSTEA_SESSION_SECRET`

`GHOSTEA_ADMIN_PASSWORD` is not used by the Vercel function. Login is
forwarded to Render, where the database-backed admin service verifies the
credentials.

## Fixes applied
- Added `GHOSTEA_ADMIN_PASSWORD` to Render startup validation and readiness.
- Fixed `database.sql` migration ordering for legacy `ghostea_warning_history`
  and `ghostea_moderation_logs` tables: upgrade columns are now added before
  indexes reference them.
- Corrected deployment documentation so `GHOSTEA_ADMIN_PASSWORD` is clearly
  Render-only.
- Added the same variable to `render.yaml` as a secret prompt.
- Added a Vercel startup guard for `GHOSTEA_SESSION_SECRET`; the proxy no
  longer accepts a partially configured session setup.
- Removed the stale Vercel documentation entry for `GHOSTEA_ADMIN_PASSWORD`.
- Documented Vercel Root Directory = `dashboard`.
- Kept `PORT` as Render-managed.

## Validation
The source test suite passes after these changes. No new runtime dependency
or database migration was introduced.
