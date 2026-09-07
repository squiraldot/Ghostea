from datetime import datetime, timezone

from telegram import ChatMember
from telegram.constants import ChatMemberStatus

from ghostea.services.chat_context import build_chat_context
from ghostea.services.telegram_service import (
    ban_member,
    mute_member,
    unban_member,
    unmute_member,
    is_admin,
    perform_ban_member, perform_mute_member, perform_unban_member, perform_unmute_member,
)


class UserManagementService:
    SCOPE = "chat_wide"

    """Administrative user-management operations for one Telegram chat.

    User state and administrative actions are chat-wide. A forum topic may be
    the place where a command was issued, but it never changes the target's
    membership, warnings, mute, ban, or reputation scope.
    """

    def __init__(self, store, bot, permission_service=None):
        self.store = store
        self.bot = bot
        self.permission_service = permission_service

    async def profile(self, chat_id, user_id):
        data = await self.store.get_user_profile(chat_id, user_id)

        try:
            member = await self.bot.get_chat_member(chat_id, user_id)
            data["telegram"] = {
                "status": member.status,
                "is_member": member.status
                in (
                    ChatMemberStatus.MEMBER,
                    ChatMemberStatus.ADMINISTRATOR,
                    ChatMemberStatus.OWNER,
                    ChatMemberStatus.RESTRICTED,
                ),
                "user": {
                    "id": member.user.id,
                    "username": member.user.username,
                    "first_name": member.user.first_name,
                    "last_name": member.user.last_name,
                    "is_bot": member.user.is_bot,
                },
            }
        except Exception:
            data["telegram"] = None

        return data

    async def _guard_target(self, chat_id, target_user_id):
        # Fail closed when Telegram cannot tell us the target's status. A
        # transient API failure must never become permission to moderate an
        # unknown account that could be an administrator.
        try:
            member = await self.permission_service.member(
                await self.bot.get_chat(chat_id), target_user_id
            ) if self.permission_service is not None else await self.bot.get_chat_member(chat_id, target_user_id)
        except Exception:
            return False, "target_lookup_failed"

        if member.status in (
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
        ):
            return False, "target_is_admin"

        return True, ""

    async def warn(self, chat_id, target_user_id, admin_user_id, reason):
        allowed, error = await self._guard_target(chat_id, target_user_id)
        if not allowed:
            raise PermissionError(error)

        member = await self.bot.get_chat_member(chat_id, target_user_id)
        count, action = await self._warning_for_member(
            chat_id, member.user, reason
        )
        await self.store.log_user_admin_action(
            chat_id, target_user_id, admin_user_id, "WARN",
            f"reason={reason};count={count};action={action}",
        )
        profile = await self.profile(chat_id, target_user_id)
        profile["admin_action"] = {
            "requested": "warn",
            "warning_count": count,
            "result": "success" if not str(action).endswith("_failed") else "punishment_failed",
            "action": action,
        }
        return profile

    async def _warning_for_member(self, chat_id, user, reason):
        # Keep the same warning policy as Telegram /warn.
        from ghostea.services.phase3_moderation import Phase3ModerationService
        service = Phase3ModerationService(self.store, self.bot, self.permission_service)
        # A lightweight chat adapter is unnecessary: the bot's Chat object
        # provides the same moderation methods required by the service.
        chat = await self.bot.get_chat(chat_id)
        return await service.issue_warning(chat, user, reason, "dashboard")

    async def reset_warnings(self, chat_id, target_user_id, admin_user_id):
        allowed, error = await self._guard_target(chat_id, target_user_id)
        if not allowed:
            raise PermissionError(error)
        await self.store.reset_warnings(chat_id, target_user_id)
        await self.store.log_user_admin_action(
            chat_id, target_user_id, admin_user_id, "RESET_WARNINGS"
        )
        return await self.profile(chat_id, target_user_id)

    async def remove_warning(self, chat_id, target_user_id, admin_user_id):
        allowed, error = await self._guard_target(chat_id, target_user_id)
        if not allowed:
            raise PermissionError(error)
        count = await self.store.remove_warning(chat_id, target_user_id)
        await self.store.log(
            chat_id, target_user_id, "UNWARN", "Dashboard removed warning", ""
        )
        await self.store.log_user_admin_action(
            chat_id, target_user_id, admin_user_id, "UNWARN",
            f"remaining={count}",
        )
        return await self.profile(chat_id, target_user_id)

    async def ban(self, chat_id, target_user_id, admin_user_id):
        allowed, error = await self._guard_target(chat_id, target_user_id)
        if not allowed:
            raise PermissionError(error)
        chat = await self.bot.get_chat(chat_id)
        result = await perform_ban_member(chat, target_user_id, self.permission_service)
        if not result.ok:
            raise PermissionError(f"ban_failed:{result.status.value}")
        await self.store.log(chat_id, target_user_id, "BAN", "Dashboard ban", "")
        await self.store.log_user_admin_action(
            chat_id, target_user_id, admin_user_id, "BAN"
        )
        return await self.profile(chat_id, target_user_id)

    async def unban(self, chat_id, target_user_id, admin_user_id):
        chat = await self.bot.get_chat(chat_id)
        result = await perform_unban_member(chat, target_user_id, self.permission_service)
        if not result.ok:
            raise PermissionError(f"unban_failed:{result.status.value}")
        await self.store.log(chat_id, target_user_id, "UNBAN", "Dashboard unban", "")
        await self.store.log_user_admin_action(
            chat_id, target_user_id, admin_user_id, "UNBAN"
        )
        return await self.profile(chat_id, target_user_id)

    async def mute(self, chat_id, target_user_id, admin_user_id, minutes):
        chat = await self.bot.get_chat(chat_id)
        chat_context = build_chat_context(chat)
        capabilities = chat_context.capabilities if chat_context else None
        if not capabilities or not capabilities.supports_member_restriction:
            raise PermissionError("member_restriction_not_supported_for_basic_group")
        allowed, error = await self._guard_target(chat_id, target_user_id)
        if not allowed:
            raise PermissionError(error)
        result = await perform_mute_member(chat, target_user_id, minutes, self.permission_service)
        if not result.ok:
            raise PermissionError(f"mute_failed:{result.status.value}")
        await self.store.log(chat_id, target_user_id, "MUTE", "Dashboard mute",
                             f"minutes={minutes}")
        await self.store.log_user_admin_action(
            chat_id, target_user_id, admin_user_id, "MUTE",
            f"minutes={minutes}",
        )
        return await self.profile(chat_id, target_user_id)

    async def unmute(self, chat_id, target_user_id, admin_user_id):
        chat = await self.bot.get_chat(chat_id)
        chat_context = build_chat_context(chat)
        capabilities = chat_context.capabilities if chat_context else None
        if not capabilities or not capabilities.supports_member_restriction:
            raise PermissionError("member_restriction_not_supported_for_basic_group")
        allowed, error = await self._guard_target(chat_id, target_user_id)
        if not allowed:
            raise PermissionError(error)
        result = await perform_unmute_member(chat, target_user_id, self.permission_service)
        if not result.ok:
            raise PermissionError(f"unmute_failed:{result.status.value}")
        await self.store.log(chat_id, target_user_id, "UNMUTE", "Dashboard unmute", "")
        await self.store.log_user_admin_action(
            chat_id, target_user_id, admin_user_id, "UNMUTE"
        )
        return await self.profile(chat_id, target_user_id)
