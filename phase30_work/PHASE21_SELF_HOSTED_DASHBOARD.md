# Phase 21 — Self-Hosted Dashboard

Ghostea now supports an all-in-one self-hosted deployment: bot/API, PostgreSQL, local storage, and dashboard can run on the same VPS.

## Behavior

- `GHOSTEA_DASHBOARD_HOST=vps` serves the existing dashboard UI from the Ghostea Python service.
- The browser uses same-origin `/api/ghostea` requests, so no Vercel deployment is required.
- VPS dashboard login creates an HttpOnly, Secure, SameSite=Lax session signed with `GHOSTEA_SESSION_SECRET`.
- Authenticated dashboard requests are converted into the same trusted API identity headers used by the Vercel proxy.
- `GHOSTEA_PROXY_SIGNING_SECRET` remains separate from the dashboard session secret.
- Managed `vercel` mode continues to use `dashboard/api/ghostea.js` and is unchanged.

## Security

- Session secret must be at least 32 characters in self-hosted mode.
- Dashboard API key and proxy signing secret remain server-side.
- Only the dashboard root/index is served as static content; arbitrary filesystem paths are never exposed.
- Dashboard responses use no-store, anti-framing, MIME-sniffing, referrer, HSTS, and CSP headers.
