# Phase H08 — Migration & Chat Lifecycle Hardening

H08 does not add user-facing features. It hardens existing Group/Supergroup
migration and lifecycle behavior against Telegram's authoritative chat state.

## Guarantees

- Group -> Supergroup migration is journaled and resumable.
- The migration update is never treated as proof of the new chat's complete
  identity; Telegram `getChat` is fetched and reconciled after migration.
- `chat_type`, `username`, visibility and forum state are refreshed from the
  current Telegram Chat object.
- Bot permission caches are invalidated across both old and new chat ids.
- `my_chat_member` lifecycle events invalidate authorization state and reconcile
  current group/supergroup identity.
- Temporary Telegram read failures do not fabricate a verified migration.
- Existing durable state remains resumable if reconciliation fails.
- Forum/topic history is preserved; losing forum capability retires stale topic
  operational state rather than deleting history.
- No new moderation or dashboard feature is introduced.

Telegram's Bot API documents `migrate_to_chat_id` / `migrate_from_chat_id` as
migration identifiers and notes that they can be up to 52 significant bits;
Ghostea stores chat ids in PostgreSQL `bigint`. The current Telegram chat object
remains authoritative after the migration.
