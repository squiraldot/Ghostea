# Phase 5 — Member Moderation Hardening

## Scope

Phase 5 hardens member-target safety across Telegram commands, automatic moderation, and dashboard user-management actions.

### Guarantees

- Destructive member actions perform a live, forced membership/role check immediately before execution when the permission service is available.
- Telegram administrators and owners are never valid punishment targets.
- Bot accounts are never valid punishment targets.
- Manual commands cannot punish the requesting admin themselves.
- Departed/left/restricted-invalid target states fail closed instead of being treated as ordinary members.
- Automatic warning/punishment revalidates the target after the message-time admin check, closing the promotion/departure race.
- Unban remains separate: a banned user is not required to be an active member before `unbanChatMember`.
- Basic groups retain the existing capability boundary: individual mute/restrict is unsupported; warning state and supported bans remain valid.
- Dashboard member actions use the same centralized target guard rather than a weaker duplicate check.

## Database / deployment

- `database.sql`: **DO NOT rerun**. No schema change was made in Phase 5.
- Render: **YES — redeploy** because Python moderation code changed.
- Vercel: **NO**, unless dashboard source is independently changed.
- UptimeRobot: **NO config change**. Keep the existing health check.

## Real Telegram testing

Use a disposable test group/supergroup first:

1. Bot is administrator with the required moderation permissions.
2. `/ban` on a normal member succeeds.
3. `/mute 10m` on a normal supergroup member succeeds.
4. `/unmute` restores the current group default permissions.
5. Attempt `/ban` or `/mute` on another administrator — action must be rejected.
6. Attempt the same against the group owner — action must be rejected.
7. Attempt to target the bot — action must be rejected.
8. Attempt to target yourself as the requesting admin — action must be rejected.
9. Remove/leave a target before a moderation action — action must fail closed.
10. Promote a target to admin immediately before an action — action must fail closed.
11. Verify automatic warning/flood moderation never punishes an administrator after a role change race.
12. Test both a basic group and a supergroup; verify the basic-group mute restriction boundary remains explicit.

## Test status

Focused Phase 5 target-safety tests cover active members, admins, owners, bots, self-targeting, and departed members. Full-suite results must only be reported from an environment where the pinned Telegram dependency is installed.
