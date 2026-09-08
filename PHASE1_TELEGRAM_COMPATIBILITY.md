# Phase 1 — Telegram Compatibility Audit

## Baseline
- Telegram Bot API contract: 10.3
- python-telegram-bot: 22.8 (pinned)
- `my_chat_member` / `chat_member`: `ChatMemberHandler`
- Polling: `Update.ALL_TYPES` (includes lifecycle updates required by Ghostea)

## Verified
- `ChatMemberStatus.OWNER == "creator"`
- `ChatMemberStatus.ADMINISTRATOR == "administrator"`
- PTB exposes `UpdateType.MY_CHAT_MEMBER` and `UpdateType.CHAT_MEMBER`
- Existing application registers both update families with `ChatMemberHandler`
- Edited messages are registered separately
- Telegram's current API documents `getChatMember` as the live membership check and `can_manage_topics` / `can_delete_messages` as the relevant topic rights.

## Decision
The project pins PTB 22.8 for the production-readiness track. A future PTB upgrade must be an explicit compatibility task, not an incidental dependency upgrade.

## Not changed
`allowed_updates=Update.ALL_TYPES` remains intentional. PTB's documentation explicitly supports this pattern, and Ghostea needs lifecycle updates such as `chat_member` for permission/cache invalidation.
