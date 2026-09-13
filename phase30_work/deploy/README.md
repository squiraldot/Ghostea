# Ghostea Self-Hosted Deployment

Phase 15 prepares the existing Ghostea backend for a normal Linux server.
This phase does **not** perform a live server migration.

## Option A — Docker

1. Install Docker/Compose on the server.
2. Copy the repository to `/opt/ghostea`.
3. Create `/opt/ghostea/.env` from `.env.example`.
4. Set all required Render-side variables:
   - `BOT_TOKEN`
   - `SUPABASE_URL`
   - `SUPABASE_KEY`
   - `DASHBOARD_API_KEY`
   - `DASHBOARD_ORIGIN`
   - `GHOSTEA_PROXY_SIGNING_SECRET`
5. Run:
   `docker compose -f docker-compose.selfhost.yml up -d --build`
6. Check:
   `curl http://127.0.0.1:10000/health`

The container runs as an unprivileged user, drops Linux capabilities, uses a
read-only root filesystem, and persists only `/app/data`.

## Option B — systemd + Python venv

1. Create user `ghostea`.
2. Place source at `/opt/ghostea`.
3. Create `/opt/ghostea/.venv` and install `requirements.txt`.
4. Put secrets in `/etc/ghostea/ghostea.env` with mode `0600`.
5. Review and install `deploy/systemd/ghostea.service`.
6. Start with systemd and verify `/health`.

## Reverse proxy

Use `deploy/nginx/ghostea.conf` as a starting point. Replace the example
hostname/certificate paths and terminate TLS at nginx. Keep the Python port
bound to localhost or otherwise firewalled from the public internet.

## Operational rules

- Keep Supabase external; no local database is introduced.
- Keep the Vercel dashboard during Phase 15 if desired.
- Set `DASHBOARD_ORIGIN` to the actual dashboard origin.
- Do not put `SUPABASE_KEY`, `BOT_TOKEN`, dashboard keys, or proxy signing
  secrets in Git.
- Configure a server firewall to expose only SSH and HTTPS (plus any
  intentionally required ports).
- Keep at least one rollback copy of the previous release.
- Use an external uptime monitor against `/health`.

## Telegram mode

Ghostea currently uses the same long-polling application entry point on a
self-hosted server. No Telegram webhook migration is introduced in Phase 15.


## Phase 19 — Storage Providers

Managed deployments can use Supabase Storage (`GHOSTEA_STORAGE_PROVIDER=supabase`). Create the configured bucket (default `ghostea`) and keep the server-side `SUPABASE_KEY` secret. Custom deployments can use `s3` with the Phase 19 S3 environment variables. Self-hosted mode continues to require local storage. Storage provider selection is explicit and does not silently fall back.
