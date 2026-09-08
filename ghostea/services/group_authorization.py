"""Phase 2 — multi-group / multi-admin Telegram authorization.

The deployment owner and Telegram group admins are intentionally separate
identities.  This service resolves which registered groups a Telegram user
can manage *right now*, using live Telegram membership data.

The database registry only identifies groups linked to this bot instance; it
never grants access by itself.
"""

from dataclasses import dataclass
from typing import Optional

from telegram.constants import ChatMemberStatus, ChatType

from ghostea.services.permission_service import (
    PermissionLookupError,
    TelegramPermissionService,
)


@dataclass(frozen=True)
class AuthorizedGroup:
    chat_id: int
    title: str
    chat_type: str
    is_forum: bool
    username: Optional[str]
    visibility: str
    bot_is_admin: bool


class GroupAuthorizationService:
    """Resolve per-user group access for a single Ghostea bot deployment."""

    def __init__(self, store, permission_service: TelegramPermissionService):
        self.store = store
        self.permission_service = permission_service

    async def list_authorized_groups(self, user_id: int, *, limit: int = 500):
        """Return groups where both bot and user have the required access.

        This is fail-closed.  A Telegram lookup failure excludes the group
        rather than granting access based on stale/local registry state.
        ``force=True`` is used for the user's membership because this method
        is intended for security-sensitive workflow entry points such as
        /uploadconfig and /uploadflag.
        """
        user_id = int(user_id)
        rows = await self.store.list_registered_chats(limit=limit)
        result = []

        for row in rows:
            try:
                chat_id = int(row["chat_id"])
                chat_type = str(row.get("chat_type") or "")
                if chat_type not in (ChatType.GROUP, ChatType.SUPERGROUP):
                    continue

                # Telegram guarantees getChatMember for other users when the
                # bot is an administrator.  Check the bot first so a private
                # or stale registry entry cannot become an authorization path.
                chat = await self.permission_service.error_policy.call_read(
                    self.permission_service.bot.get_chat,
                    chat_id,
                    scope_id=chat_id,
                )
                bot_permissions = await self.permission_service.bot_permissions(
                    chat, force=False
                )
                if not bot_permissions.is_admin:
                    continue

                member = await self.permission_service.member(
                    chat, user_id, force=True
                )
                if member.status not in (
                    ChatMemberStatus.ADMINISTRATOR,
                    ChatMemberStatus.OWNER,
                ):
                    continue

                result.append(
                    AuthorizedGroup(
                        chat_id=chat_id,
                        title=str(row.get("title") or f"Chat {chat_id}"),
                        chat_type=chat_type,
                        is_forum=bool(row.get("is_forum", False)),
                        username=row.get("username"),
                        visibility=str(row.get("visibility") or "private"),
                        bot_is_admin=True,
                    )
                )
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
            except PermissionLookupError:
                # Unknown Telegram state is not authorization.
                continue
            except Exception:
                # This method is used for a user-facing group picker. One
                # inaccessible/stale group must not expose or block others.
                continue

        return result

    async def is_user_admin(self, chat, user_id: int, *, force: bool = True):
        """Live per-chat admin check with fail-closed error semantics."""
        try:
            member = await self.permission_service.member(
                chat, int(user_id), force=force
            )
        except PermissionLookupError:
            return False

        return member.status in (
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
        )
