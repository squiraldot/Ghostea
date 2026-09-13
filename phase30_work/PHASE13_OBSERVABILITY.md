# Phase 13 — Production Observability

Phase 13 extends the existing bounded H12 telemetry into operational metrics
that help diagnose dashboard, Telegram, and database performance without
changing moderation decisions.

## Included

- Bounded in-process structured event buffer.
- Recursive secret-field redaction.
- Request/correlation IDs for Telegram and dashboard HTTP requests.
- HTTP response status + aggregate latency metrics.
- Telegram action aggregate latency metrics.
- Supabase request/error events and aggregate latency metrics.
- `/api/diagnostics` continues to expose bounded telemetry to authenticated
  dashboard operators.
- Telemetry payloads are capped and credentials/cookies are excluded.
- Existing `/health` and moderation behavior remain unchanged.

## Metrics

`http_request`, `telegram_action`, and `supabase_request` expose aggregate
`count`, `total_ms`, `avg_ms`, and `max_ms` values. Raw request bodies, headers,
tokens, passwords, API keys, cookies, and Supabase keys are not recorded.

## Deployment

No database migration is required.

- Render redeploy: required.
- Vercel redeploy: not required for backend telemetry changes, but recommended
  if the dashboard source is deployed from the same release.
- UptimeRobot: unchanged.
