# Phase 7 — Dashboard Group Linking

## Why
Telegram Bot API does not provide a method to enumerate every group a bot belongs to. Ghostea therefore uses explicit dashboard linking as the deterministic source of known groups.

## Flow
1. Dashboard admin enters numeric Telegram Group ID.
2. Backend calls Telegram `getChat`.
3. Backend verifies the chat is a group/supergroup.
4. Backend verifies the bot is currently a member and administrator.
5. Registry is persisted as `is_linked=true` and default group settings are materialized.
6. `/uploadconfig` and `/uploadflag` enumerate linked registry rows and perform live user-admin authorization with `getChatMember`; `getChatAdministrators` is a fallback for the user check.

Dashboard linking never grants Telegram-user authorization. A Telegram user must still be a current group administrator.

## Deployment
- Run the additive `database.sql` section for `is_linked` and `linked_by` once.
- Redeploy Render.
- Redeploy Vercel because the dashboard UI/proxy changed.
- No UptimeRobot configuration change.

## Telegram test
- Bot is admin in test group.
- Dashboard > Groups > Add Group > paste numeric ID > Verify & Link.
- Confirm group appears.
- As group admin, DM `/uploadconfig` and `/uploadflag`; group must appear.
- As normal member, same commands must not show the group.
- Remove bot from group; dashboard group disappears after lifecycle update.
- Re-add/promote bot; group can be linked again.
