# Phase H14 — Adversarial Regression Testing

H14 is a stabilization-only hardening layer. It adds a deterministic, offline
failure-injection harness around the Telegram/action/recovery boundaries.

## Covered adversarial cases

- Telegram `403`, `400`, and `429` failures on destructive actions
- transient timeout recovery for safe reads
- concurrent duplicate update delivery
- bot demotion / authorization-cache invalidation
- Group → Supergroup migration with incomplete authoritative reconciliation
- stale forum-topic handling boundary
- concurrent moderation of the same `(chat_id, user_id)` target
- Supabase/persistence failure must not become a successful Telegram action
- restart recovery ordering
- anonymous/chat-backed `sender_chat` identity safety

The harness never calls Telegram, Supabase, or external services. It is safe to
run in CI and is also included in local production-readiness checks.

## Safety invariant

A transient or authorization failure may reduce availability, but it must not
be converted into a false success, an unintended retry loop, or a destructive
action against an uncertain identity/target.
