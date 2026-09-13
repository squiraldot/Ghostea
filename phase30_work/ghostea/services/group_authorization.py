import logging
from dataclasses import dataclass
from typing import Optional

from telegram.constants import ChatMemberStatus, ChatType

logger = logging.getLogger("Ghostea")


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
    """Resolve per-user access for explicitly linked Ghostea groups.

    The upload workflow intentionally follows Telegram's direct Bot API model:
    dashboard/registry decides *which chats are candidates*; Telegram decides
    whether the requester is an administrator *right now*.  We use
    getChatMember first and getChatAdministrators as a reliable second path.
    No dashboard role or stale database permission can grant Telegram access.
    """

    def __init__(self, store, permission_service):
        self.store = store
        self.permission_service = permission_service
        self.bot = permission_service.bot

    @staticmethod
    def _is_admin(member) -> bool:
        return str(getattr(member, "status", "")) in (
            str(ChatMemberStatus.ADMINISTRATOR),
            str(ChatMemberStatus.OWNER),
            "administrator",
            "creator",
        )

    async def _admin_list(self, chat_id: int):
        """Fetch the live administrator list for an already-linked chat."""
        return await self.bot.get_chat_administrators(int(chat_id))

    async def _user_is_admin(self, chat_id: int, user_id: int) -> bool:
        """Check the actual Telegram user using the live admin list first."""
        try:
            admins = await self._admin_list(chat_id)
            return any(
                int(getattr(getattr(admin, "user", None), "id", -1)) == int(user_id)
                and self._is_admin(admin)
                for admin in admins
            )
        except Exception:
            # Fallback to the canonical individual lookup if the admin-list
            # request is temporarily unavailable. Telegram documents both
            # methods; getChatMember is guaranteed for other users when the
            # bot is an administrator.
            try:
                member = await self.bot.get_chat_member(chat_id, int(user_id))
                return self._is_admin(member)
            except Exception:
                logger.warning(
                    "Could not verify Telegram admin user=%s chat=%s via either API path",
                    user_id, chat_id, exc_info=True,
                )
                return False

    async def list_authorized_groups(self, user_id: int, *, limit: int = 500):
        """Return explicitly linked groups where the Telegram user is admin now."""
        user_id = int(user_id)
        rows = await self.store.list_linked_chats(limit=limit)
        result = []

        for row in rows:
            try:
                chat_id = int(row["chat_id"])
                chat = await self.bot.get_chat(chat_id)
                chat_type = str(getattr(chat, "type", "") or "")
                if chat_type not in (ChatType.GROUP, ChatType.SUPERGROUP):
                    continue

                # Use Telegram's live administrator list as the primary source.
                # It lets us verify both the Ghostea bot and the requesting user
                # in one authoritative call for each linked chat.
                try:
                    admins = await self._admin_list(chat_id)
                except Exception:
                    # If the list endpoint has a transient/API issue, fall back
                    # to individual member lookups.
                    try:
                        bot_member = await self.bot.get_chat_member(chat_id, self.bot.id)
                        if not self._is_admin(bot_member):
                            continue
                        if not await self._user_is_admin(chat_id, user_id):
                            continue
                    except Exception:
                        continue
                else:
                    bot_is_admin = any(
                        int(getattr(getattr(admin, "user", None), "id", -1)) == int(self.bot.id)
                        and self._is_admin(admin)
                        for admin in admins
                    )
                    if not bot_is_admin:
                        continue
                    user_is_admin = any(
                        int(getattr(getattr(admin, "user", None), "id", -1)) == user_id
                        and self._is_admin(admin)
                        for admin in admins
                    )
                    if not user_is_admin:
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
            except Exception:
                logger.warning(
                    "Upload authorization skipped linked chat=%s for user=%s",
                    row.get("chat_id"), user_id, exc_info=True,
                )
                continue

        return result

    async def is_user_admin(self, chat, user_id: int, *, force: bool = True):
        return await self._user_is_admin(int(chat.id), int(user_id))
