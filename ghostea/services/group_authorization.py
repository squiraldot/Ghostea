import logging

logger = logging.getLogger("Ghostea")

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

        # Telegram has no Bot API method that enumerates all groups a bot is
        # currently in. The registry is therefore normally populated by
        # my_chat_member and group-message lifecycle events. For upgrades from
        # older Ghostea versions, use existing group-settings rows as a
        # bootstrap candidate set. Every candidate still requires live
        # getChat + bot-admin + requester-admin checks below, so this fallback
        # never grants access by itself.
        try:
            legacy_rows = await self.store._call(
                self.store.db.select,
                "ghostea_group_settings",
                {
                    "select": "chat_id",
                    "limit": str(max(1, min(int(limit), 500))),
                },
            )
        except Exception:
            legacy_rows = []

        known = {int(r["chat_id"]): dict(r) for r in rows if r.get("chat_id") is not None}
        explicit_unlinked = {
            chat_id for chat_id, row in known.items()
            if row.get("is_linked") is False
        }
        for legacy in legacy_rows:
            try:
                chat_id = int(legacy["chat_id"])
            except (KeyError, TypeError, ValueError):
                continue
            if chat_id in explicit_unlinked or chat_id in known:
                continue
            known[chat_id] = {
                "chat_id": chat_id,
                "chat_type": None,
                "title": None,
                "username": None,
                "visibility": "private",
                "is_forum": False,
                "is_linked": True,
            }

        result = []

        for row in known.values():
            try:
                chat_id = int(row["chat_id"])
                if row.get("is_linked") is False:
                    continue

                # Telegram's getChat() is authoritative for current chat type.
                # This also repairs stale/missing registry metadata during the
                # bootstrap path used by older installations.
                chat = await self.permission_service.error_policy.call_read(
                    self.permission_service.bot.get_chat,
                    chat_id,
                    scope_id=chat_id,
                )
                chat_type = str(getattr(chat, "type", "") or "")
                if chat_type not in (ChatType.GROUP, ChatType.SUPERGROUP):
                    continue

                # Telegram guarantees getChatMember for other users when the
                # bot is an administrator.  Check the bot first so a private
                # or stale registry entry cannot become an authorization path.
                bot_permissions = await self.permission_service.bot_permissions(
                    chat, force=True
                )
                if not bot_permissions.is_admin:
                    continue

                try:
                    member = await self.permission_service.member(
                        chat, user_id, force=True
                    )
                    is_admin = member.status in (
                        ChatMemberStatus.ADMINISTRATOR,
                        ChatMemberStatus.OWNER,
                    )
                except PermissionLookupError:
                    # Defensive fallback: Telegram also exposes the complete
                    # administrator list for a known chat. This is not used
                    # as discovery; it is only a second live authorization
                    # check for the already-linked chat.
                    admins = await self.permission_service.error_policy.call_read(
                        chat.get_administrators, scope_id=chat_id
                    )
                    is_admin = any(
                        int(getattr(a.user, "id", -1)) == user_id
                        and getattr(a, "status", None) in (
                            ChatMemberStatus.ADMINISTRATOR,
                            ChatMemberStatus.OWNER,
                        )
                        for a in admins
                    )
                if not is_admin:
                    continue

                result.append(
                    AuthorizedGroup(
                        chat_id=chat_id,
                        title=str(getattr(chat, "title", None) or row.get("title") or f"Chat {chat_id}"),
                        chat_type=chat_type,
                        is_forum=bool(getattr(chat, "is_forum", False)),
                        username=getattr(chat, "username", None) or row.get("username"),
                        visibility=("public" if getattr(chat, "username", None) else "private"),
                        bot_is_admin=True,
                    )
                )
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
            except PermissionLookupError as exc:
                logger.warning("Upload authorization lookup failed for chat=%s: %s", row.get("chat_id"), exc)
                continue
            except Exception:
                logger.exception("Upload authorization unexpected failure for chat=%s", row.get("chat_id"))
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
