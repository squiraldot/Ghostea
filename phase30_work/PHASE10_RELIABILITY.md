# Ghostea Phase 10 — Reliability

## Changes

- Telegram write operations retry only on explicit `RetryAfter` rate-limit responses.
- Network/timeout write failures are not blindly retried, preventing duplicate
  Telegram messages when the remote write may already have succeeded.
- Resource publish callbacks are serialized per session inside one worker.
- Existing durable READY -> PUBLISHING claim remains the cross-worker guard.
- Supabase GET retries are configurable and honor `Retry-After` when present.
- Supabase HTTP timeout and read retry count are configurable via environment.
- Existing `asyncio.to_thread` DB bridge keeps blocking REST I/O off the bot event loop.

## New optional environment variables

- `SUPABASE_HTTP_TIMEOUT_SECONDS` (default 15)
- `SUPABASE_READ_RETRIES` (default 3, bounded to 0–4)

No new environment variable is required for normal operation.

## Database

No Phase 10 SQL migration is required.

## Deployment

- Supabase/database.sql: **NO**
- Render: **YES**
- Vercel: **YES**
- UptimeRobot: **NO**

## Verification

Focused source tests and Python compile checks are required before live testing.
Live Telegram rate-limit/retry behavior must be verified in production/staging
without intentionally triggering abusive traffic.
