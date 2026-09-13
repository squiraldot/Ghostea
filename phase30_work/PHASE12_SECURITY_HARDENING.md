# PHASE 12 — Security Hardening

## Implemented
- Dashboard session cookies remain `HttpOnly`, `Secure`, `SameSite=Lax`, with an 8-hour TTL.
- Session timestamps now reject future-issued cookies.
- Dashboard API responses include security headers and `no-store` caching.
- Dashboard login has a bounded per-source-IP rate limiter (10 attempts/minute per serverless instance).
- Vercel now signs the authenticated dashboard identity with `GHOSTEA_PROXY_SIGNING_SECRET`.
- Render verifies that signature before accepting `X-Ghostea-Admin-*` identity headers, preventing header forgery/replay when only the dashboard API key is known.
- Existing DB-backed admin authorization is still performed on protected requests, so disabled/deleted/role-changed admins fail closed.
- Existing password storage uses salted `scrypt` and constant-time digest comparison.
- Existing request body limits, allowlists, origin checks, role checks, and fail-closed input validation are retained.

## New environment variable
Set the same high-entropy random value in both Render and Vercel:

`GHOSTEA_PROXY_SIGNING_SECRET`

This is intentionally separate from `DASHBOARD_API_KEY` and `GHOSTEA_SESSION_SECRET`.

## Database
No Phase 12 SQL migration is required.

## Deployment
1. Render: add `GHOSTEA_PROXY_SIGNING_SECRET`, then redeploy.
2. Vercel: add the exact same `GHOSTEA_PROXY_SIGNING_SECRET`, then redeploy.
3. UptimeRobot: no change; `/health` remains public.

## Security boundary
The Render API key authenticates the Vercel proxy. The new proxy signature authenticates the admin identity carried through that proxy. Both checks are required.
