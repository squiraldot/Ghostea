# Phase 4 — Forum / Topics Hardening

## Scope

Phase 4 hardens Telegram forum-topic semantics without changing the database schema.

### Changes
- Telegram forum **General** is represented as topic ID `1` even though ordinary General messages do not carry `message_thread_id`.
- Basic groups and non-forum supergroups remain chat-scoped and never become topic-scoped.
- Topic registry access remains keyed by `(chat_id, topic_id)`; a topic ID is never treated as globally unique.
- A fresh forum seeds the local General-topic registry row so topic selectors can work before a custom-topic event has been observed.
- Added a `list_selectable_topics()` API for future upload/resource workflows. It excludes inactive, closed, and hidden topics.
- Topic icon colors are validated against the Telegram Bot API's currently allowed values before calling Telegram.
- Existing lifecycle handling remains authoritative through Telegram API calls; local lifecycle state is updated only after successful operations or definitive stale-topic errors.

## Telegram compatibility notes

Telegram documents General as a special non-deletable topic with ID `1`; ordinary General messages do not carry a thread ID. Forum topic operations are scoped by `chat_id + message_thread_id`, and supergroup topic-management operations require the corresponding administrator permissions. Telegram also does not expose a Bot API method for enumerating all forum topics, so Ghostea's selector is based on its observed topic registry and must revalidate the selected topic immediately before any future publish/upload.

## Deployment checklist

- **database.sql:** **NO** — no schema change in Phase 4. Do not rerun the full schema just for this phase.
- **Render:** **YES** — Python source changed; redeploy the bot.
- **Vercel:** **NO** — dashboard source was not changed.
- **UptimeRobot:** **NO** — keep the existing health check/configuration.

## Real Telegram testing

Use a disposable forum supergroup first:
1. Verify the bot is an administrator with **Manage Topics** and **Delete Messages** where required.
2. Send a message in **General** and verify Ghostea resolves topic ID `1`.
3. Create two custom topics and send messages in both; verify each receives its own topic-scoped state.
4. Rename, close, reopen, and delete one custom topic; verify the registry state changes correctly.
5. Hide and unhide General; verify `is_hidden` and closed/open state are updated.
6. Try the same numeric topic ID in two different test forums; verify state never crosses chats.
7. Convert a disposable basic group to a supergroup/forum only after migration tests are complete; verify old chat state remains isolated and topic state starts under the new chat ID.
8. Restart/redeploy the bot and verify persisted topic state is still correct.

## Testing

Focused Phase 4 tests are in `tests/test_phase4_forum_topics_hardening.py`.
