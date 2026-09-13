# Phase H07 Change Log

- Added explicit General topic hidden/unhidden lifecycle persistence.
- Added `is_hidden` to `ghostea_topic_registry`.
- Added safe stale-topic retirement for definitive Telegram topic-id/not-found errors.
- Preserved topic names and lifecycle state across close/reopen/edit events.
- Kept General topic ID 1 non-deletable.
- Documented Bot API limitation: no dedicated topic-deleted update is exposed to bots.
- No new user-facing topic capability was added.
