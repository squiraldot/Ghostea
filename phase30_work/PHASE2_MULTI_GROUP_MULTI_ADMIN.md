# Phase 2 — Multi-Group / Multi-Admin Hardening

## Scope

One Ghostea bot deployment may be installed in multiple Telegram groups/supergroups. The server owner is not treated as a Telegram group administrator.

Authorization is evaluated per Telegram user and per target chat.

## Rules

1. `ghostea_chat_registry` identifies chats linked/known to this bot deployment.
2. Registry membership is **not** an authorization grant.
3. For security-sensitive group selection, the bot verifies its own admin status in the chat.
4. The requesting Telegram user is then checked live with `getChatMember`.
5. Only `creator` / `administrator` users are eligible.
6. Lookup failures fail closed.
7. One inaccessible/stale group does not prevent other eligible groups from being returned.
8. Later `/uploadconfig` and `/uploadflag` workflows will use this service before displaying group buttons.

## Telegram contract

Telegram documents that `getChatMember` is guaranteed to work for other users when the bot is an administrator in the chat. Therefore Ghostea checks bot administration before using a user's live membership result as an authorization decision.

## Implementation

- `ghostea/storage/phase3_store.py`
  - added `list_registered_chats()`
- `ghostea/services/group_authorization.py`
  - added `GroupAuthorizationService`
  - added `AuthorizedGroup`
- `ghostea/app.py`
  - registers the service in `application.bot_data["group_authorization"]`

No dashboard-admin role is reused for Telegram group authorization.

## Next phase dependency

The future DM upload workflows will call:

`application.bot_data["group_authorization"].list_authorized_groups(user_id)`

and then independently revalidate the selected `chat_id` and `topic_id` immediately before publishing.
