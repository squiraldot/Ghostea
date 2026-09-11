# Phase 11 — 50K+ Load & Scale Hardening

## Changes
- Added idempotent indexes for moderation logs, user directory, join events,
  topic registry, and resource monitoring.
- Moderation history queries can use chat/time and chat/user/time indexes.
- User-directory activity writes are throttled with a configurable 5-minute
  default (`GHOSTEA_USER_DIRECTORY_TOUCH_SECONDS`).
- Dashboard-facing list limits are capped to 200 to avoid oversized API payloads.
- Existing process-local caches and durable DB state remain the source-of-truth
  split; no per-message unbounded in-memory growth was introduced.

## Database
**YES — run the complete database.sql once.**
Phase 11 migration is additive and uses `CREATE INDEX IF NOT EXISTS`.

## Optional Render environment
`GHOSTEA_USER_DIRECTORY_TOUCH_SECONDS=300`

Do not set this below 30 seconds.

## Deployment
- Supabase/database.sql: YES
- Render: YES
- Vercel: YES
- UptimeRobot: NO

## Verification
Focused tests must pass. Real Telegram smoke test should include a high-traffic
group, forum topic traffic if applicable, moderation, and dashboard resources.
