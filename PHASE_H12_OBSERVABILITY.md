# Phase H12 — Production Observability & Diagnostics

Ghostea now has bounded structured operational observability without changing moderation decisions.

## Included
- Correlation/request IDs for Telegram updates and dashboard HTTP requests.
- Bounded in-process event buffer and counters.
- Secret-field redaction for observability payloads.
- Telegram action outcome events from the H03 action layer.
- Telegram read/error events from H05 retry policy.
- Bot/member lifecycle events from H02/H08 handlers.
- Authenticated `/api/diagnostics` endpoint with bounded recent events.
- Existing `/health` and `/api/health` behavior is unchanged.

## Event categories
`update_received`, `duplicate_update`, `telegram_action`, `telegram_error`,
`bot_membership_change`, `member_status_change`, `http_request`.

The event buffer is intentionally process-local and bounded. It is diagnostic
telemetry, not durable application state and is not used for moderation decisions.
No bot tokens, authorization headers, passwords, API keys, or secrets are recorded.

## Production note
For multi-process deployments, this in-memory diagnostic buffer is per-process.
The current architecture remains single-process coordinated; external log
aggregation can consume the structured log lines if needed.
