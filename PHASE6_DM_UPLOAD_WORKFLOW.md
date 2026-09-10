# Phase 6 — DM Upload Workflow Engine

## Scope

Implements the shared state machine for `/uploadconfig` and `/uploadflag` in bot DMs.
The engine persists short-lived workflow sessions in `ghostea_upload_sessions` and revalidates
Telegram admin access and forum-topic availability at the final confirmation boundary.

## Flow

### `/uploadconfig`

1. Linked groups where the requester is currently a Telegram admin are listed.
2. Group selection is shown.
3. Forum groups show currently selectable topics; non-forum groups skip topic selection.
4. File or URL is selected.
5. Source is received.
6. Mandatory caption is collected.
7. Mandatory description is collected.
8. Confirm / Cancel is shown.
9. Confirm moves the session to `READY`; Telegram publishing is intentionally Phase 7.

### `/uploadflag`

The same group/topic selection is used, followed by image, Main-Flag, Sub-Flags, description,
and Confirm / Cancel.

## Safety boundaries

- Session IDs are opaque and short-lived (15 minutes).
- Callback ownership is checked against Telegram user ID.
- Expired, cancelled and ready sessions cannot be mutated.
- Group admin authorization is rechecked at selection and confirmation.
- Forum topic availability is rechecked before confirmation.
- Topic IDs are scoped to their chat.
- Exactly one resource source is accepted: file OR URL.
- Caption and description are mandatory.
- No Telegram publish side effect happens in Phase 6; Phase 7 owns publishing.

## Deployment/testing checklist

- **database.sql:** YES — run the additive Phase 6 section once in Supabase. Do not rerun destructive/reset SQL.
- **Render:** YES — redeploy the bot because Python workflow code changed.
- **Vercel:** NO — no dashboard/frontend change in this phase.
- **UptimeRobot:** NO — keep the existing `/health` monitor unchanged.
- **Telegram:** test both commands in DM using a test group, a non-forum supergroup, and a forum supergroup.
