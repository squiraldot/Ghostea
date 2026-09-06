# H15 Deployment Fix

## Fixed

### Render startup crash
The H15 source used:

- `filters.StatusUpdate.MY_CHAT_MEMBER`
- `filters.StatusUpdate.CHAT_MEMBER`

Those attributes are not available in python-telegram-bot 22.8. The bot
therefore crashed during `create_application()` before polling started.

The handlers now use `TypeHandler(Update, ...)` wrappers that explicitly
dispatch only when `update.my_chat_member` or `update.chat_member` is present.

### Supabase migration safety
The moderation-log `topic_id` upgrade now uses:

`ALTER TABLE IF EXISTS ghostea_moderation_logs ADD COLUMN IF NOT EXISTS topic_id bigint`

and remains before all indexes that reference `topic_id`.

## Validation

The full test suite is expected to pass with the same dependency set.
