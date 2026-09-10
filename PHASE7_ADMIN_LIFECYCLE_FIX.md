# Phase 7 Admin Authorization + Bot Lifecycle Fix

## Fixed
- Upload authorization no longer relies exclusively on the chat registry.
- It unions linked registry rows with chat-settings discovery rows, then performs
  live Telegram `getChat` + bot-admin + requester-admin checks.
- A known `is_linked=false` chat can never be resurrected from stale settings.
- `my_chat_member` marks a chat linked when the bot remains/joined and soft-unlinks
  it when Telegram reports `left` or `kicked`.
- Dashboard `/api/groups` and individual group APIs require `is_linked=true`.
- Dashboard group cache is invalidated immediately after bot removal.
- Historical moderation/settings/resource data is retained; it is not silently
  destroyed. This is deliberate so migration/audit/recovery remains possible.
- Phase 7 upload/resource tables are included in chat migration scope.

## Database
Additive migration only:
- `ghostea_chat_registry.is_linked boolean not null default true`
- Existing registry rows remain linked until Telegram lifecycle says otherwise.

Run this SQL once on existing Supabase databases.

## Deployment
- Supabase: run the new Phase 7 lifecycle SQL once.
- Render: redeploy.
- Vercel: no code redeploy unless the dashboard frontend itself changed.
- UptimeRobot: no change.

## Real Telegram tests
1. Bot admin + human admin -> `/uploadconfig` and `/uploadflag` must list the group.
2. Remove bot from group -> group disappears from dashboard immediately.
3. Existing settings/log/resource history remains in DB.
4. Re-add bot -> registry becomes linked again and group can reappear.
5. Remove bot -> stale dashboard group API returns `group_not_linked`.
6. Closed topic behavior from Phase 7 remains: reopen only when bot has
   `can_manage_topics`, then publish.
