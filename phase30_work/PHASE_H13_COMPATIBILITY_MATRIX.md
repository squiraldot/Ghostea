# Phase H13 — Telegram Compatibility Matrix

Phase H13 is a stabilization phase. It does not add user-facing moderation features.
It makes Telegram chat/update compatibility explicit and testable.

## Supported chat modes

- Basic Group: message deletion, member ban, default permissions; no per-member restriction and no Bot API unban operation.
- Supergroup: message deletion, restriction/mute, ban/unban, default permissions.
- Forum Supergroup: all applicable Supergroup operations plus topic context/lifecycle, subject to live permissions.
- Private Bot Chat: no group moderation; private topics are supported only when bot topic mode is enabled.
- Channel direct-message chat: intentionally unsupported by Ghostea moderation; fail closed even though Telegram represents it as a supergroup-shaped chat.
- Channel: outside Ghostea moderation scope.

## Operation contract

Stable compatibility and live authorization remain separate:

`ChatCapabilities` → Telegram supports the operation for this chat shape.

`TelegramPermissionService` → the bot currently has the required administrator right.

No matrix entry grants a live permission.

## Important Telegram semantics

- `banChatMember` is available in groups and supergroups (and channels), while `unbanChatMember` is only available in supergroups/channels. Therefore Basic Group unban is intentionally unsupported.
- `restrictChatMember` is supergroup-only.
- `setChatPermissions` applies to groups and supergroups and requires `can_restrict_members`.
- Forum create/edit/close/reopen require forum supergroup context and `can_manage_topics` for the bot's normal administrative path.
- `deleteForumTopic` in a supergroup requires `can_delete_messages`; private bot topics have no group admin permission requirement.
- Telegram update types not handled by Ghostea are explicitly classified as safe-to-ignore rather than interpreted as moderation messages.
- `guest_message`, `managed_bot`, and `subscription` are part of the current Bot API update surface but are outside Ghostea's moderation pipeline.

## H13 validation

The matrix is deterministic and side-effect free. Production readiness checks it without Telegram network calls.
