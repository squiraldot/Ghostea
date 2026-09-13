# Phase 29 — Background Jobs & Queue Reliability

Ghostea now has a provider-neutral durable background-job queue for work that should
not run inside Telegram update handlers.

## What is included
- `ghostea/services/background_jobs.py`: persistent at-least-once queue.
- PostgreSQL and Supabase REST providers are supported through the existing provider contract.
- Optimistic compare-and-set claims prevent normal double-claim races.
- Worker leases recover jobs left `running` after a process crash.
- Bounded exponential retries and a terminal `dead` state.
- Payload size and attempt limits.
- Graceful worker shutdown.
- Built-in `expire_upload_sessions` maintenance job, scheduled durably.
- Observability events for enqueue/success/failure.
- Migration `0011_background_jobs.sql`.

## Delivery semantics
The queue is **at-least-once**, not exactly-once. A handler may run again after a
worker crash, so handlers must be idempotent. Telegram writes are not automatically
moved into this queue because non-idempotent Telegram operations need the existing
Phase 10 write policy.

## Deployment
No new secret is required. The worker is enabled by default.

Optional settings:
- `GHOSTEA_JOB_WORKER_ENABLED=true`
- `GHOSTEA_JOB_WORKER_POLL_SECONDS=2`
- `GHOSTEA_JOB_LEASE_SECONDS=120`
- `GHOSTEA_JOB_MAX_ATTEMPTS=5`
- `GHOSTEA_JOB_BATCH_SIZE=1`
- `GHOSTEA_JOB_PAYLOAD_MAX_BYTES=65536`

Existing databases must run migration 11. Fresh installs using `database.sql` are
created with the queue table and schema version 11.
