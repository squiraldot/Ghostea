# Phase H09 — State Recovery & Consistency

Phase H09 hardens recovery of existing Ghostea state. It adds no user-facing
features.

## Recovery model

- Supabase is durable Ghostea state.
- Telegram is authoritative for Telegram-owned state such as membership,
  permissions, and current chat state.
- Process-local caches and anti-spam windows are disposable.
- Startup recovery clears runtime caches before reading durable security state.
- Persisted anti-raid locks and verification records are retried safely after
  transient Telegram failures instead of being discarded.

## Security recovery guarantees

- A transient `429`, timeout, network, or Telegram server failure does not
  delete an expired verification record.
- A transient failure while restoring an anti-raid lock does not delete the
  durable lock; the recovery loop can retry it.
- A definitive terminal Telegram response may safely clean up state when the
  Telegram-owned object is no longer actionable.
- Newer administrator changes to default chat permissions are still respected
  when an anti-raid lock expires.

## Runtime state

`Phase3Store.clear_runtime_caches()` clears settings, filters, directory,
chat/topic throttles, topic settings, and reputation lock caches.
`ProtectionService.clear_runtime_state()` clears in-memory flood, repeat, and
join windows. These are intentionally not reconstructed as durable state.

## Scope

This phase does not add persistent mute tables. Telegram timed member
restrictions remain Telegram-owned state and are reconciled by live Telegram
lookups when an operation needs authoritative state.
