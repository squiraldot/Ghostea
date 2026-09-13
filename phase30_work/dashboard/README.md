# Ghostea Admin Dashboard — Phase 8

A mobile-responsive Vercel dashboard backed by the Render Ghostea API.

## Vercel environment variables

- `GHOSTEA_API_URL` — Render service URL
- `GHOSTEA_API_KEY` — same value as Render `DASHBOARD_API_KEY`
- `GHOSTEA_ADMIN_PASSWORD` — dashboard login password
- `GHOSTEA_SESSION_SECRET` — long random session-signing secret

The browser never receives `GHOSTEA_API_KEY` or `GHOSTEA_SESSION_SECRET`.

## Phase 8 features

- Overview and group selection
- Moderation settings editor
- Protection toggles
- Custom filter management
- Analytics
- Moderation logs
- Secure session login


## Phase 21 — Self-hosted dashboard

When `GHOSTEA_DASHBOARD_HOST=vps`, the same `dashboard/index.html` is served by
the Ghostea Python server and `/api/ghostea` provides the local same-origin
session/proxy endpoint. The browser never receives `DASHBOARD_API_KEY`,
`GHOSTEA_PROXY_SIGNING_SECRET`, or `GHOSTEA_SESSION_SECRET`.

Required VPS dashboard secret:

- `GHOSTEA_SESSION_SECRET` — at least 32 random characters

The Vercel dashboard continues to use its existing serverless proxy in managed
mode; this local dashboard path is not used there.
