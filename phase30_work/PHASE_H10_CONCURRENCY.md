# Phase H10 — Resilience / Concurrency / Load

H10 hardens existing behavior without adding user-facing features.

## Guarantees
- Duplicate Telegram updates are suppressed for a bounded TTL.
- Telegram side effects are globally concurrency-limited.
- Per `(chat_id, user_id)` member mutations are serialized to prevent mute/ban/unban races.
- Runtime anti-spam maps are bounded and periodically pruned.
- Cache misses use per-key single-flight locks to avoid stampedes.
- Durable state remains in Supabase; these controls are process-local safety mechanisms.

## Intentional boundaries
- No blind retry of destructive Telegram operations.
- No assumption that process-local state is durable.
- No cross-process distributed lock is claimed; production deployments should run one
  active bot polling worker unless a distributed coordination layer is introduced.
