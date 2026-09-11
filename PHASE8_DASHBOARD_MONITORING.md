# Ghostea Phase 8 — Dashboard Monitoring

## Scope

Phase 8 monitoring extends the existing dashboard architecture with a
protected **Resources** view for published `/uploadconfig` and `/uploadflag`
resources.

The dashboard reads the durable `ghostea_resources` registry created in
Phase 7. It does not expose the Telegram bot token or Supabase server key.

## Monitoring

For the selected linked group, the dashboard shows:

- total published resources
- file/media resources
- URL resources
- flag resources
- creation timestamp
- resource type
- caption or flag metadata
- topic scope
- Telegram published message IDs
- URL source as a privileged dashboard link when the resource is a URL

Forum topic selection filters the resource list by `(chat_id, topic_id)`.
Group-wide mode shows resources for the whole chat.

## API

`GET /api/groups/<chat_id>/resources?limit=100`
`GET /api/groups/<chat_id>/resources?limit=100&topic_id=<topic_id>`

The route is protected by the existing dashboard authentication/RBAC boundary
and uses the existing `ghostea_resources` table.

## Database

No new migration is required. Phase 7's `ghostea_resources` table is reused.

## Deployment

- database.sql: **NO**
- Render: **YES**
- Vercel: **YES**
- UptimeRobot: **NO**

## Verification

Offline regression coverage checks:

- protected backend resource route
- Vercel proxy allowlist
- dashboard Resources UI and loader
- group/topic filtering contract

Live Telegram publishing and dashboard smoke tests must still be performed
against a real test group after deployment.
