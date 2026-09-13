from datetime import datetime, timedelta, timezone
import time

from telegram import ChatPermissions
from telegram.constants import ChatMemberStatus

from ghostea.services.chat_context import build_chat_context
from ghostea.services.action_result import ActionResult, ActionStatus, execute_action, set_concurrency_gate
from ghostea.services.permission_service import PermissionLookupError, TelegramPermissionService
from ghostea.services.concurrency import ConcurrencyGate
from ghostea.services.moderation_target_guard import verify_moderation_target

_ACTION_GATE = ConcurrencyGate(max_external=32, max_key_locks=20000)
set_concurrency_gate(_ACTION_GATE)


_ADMIN_CACHE = {}
_ADMIN_CACHE_TTL = 30.0


def invalidate_admin_cache(chat_id: int, user_id: int | None = None):
    chat_id = int(chat_id)
    if user_id is None:
        for key in [k for k in _ADMIN_CACHE if k[0] == chat_id]:
            _ADMIN_CACHE.pop(key, None)
    else:
        _ADMIN_CACHE.pop((chat_id, int(user_id)), None)


async def _run_keyed(chat_id, user_id, operation):
    async with await _ACTION_GATE.keyed((int(chat_id), int(user_id))):
        return await operation()


class UnsupportedChatFeature(RuntimeError):
    """Raised when Telegram does not support an operation for this chat type."""


def muted_permissions() -> ChatPermissions:
    return ChatPermissions(
        can_send_messages=False,
        can_send_audios=False,
        can_send_documents=False,
        can_send_photos=False,
        can_send_videos=False,
        can_send_video_notes=False,
        can_send_voice_notes=False,
        can_send_polls=False,
        can_send_other_messages=False,
        can_add_web_page_previews=False,
        can_change_info=False,
        can_invite_users=False,
        can_pin_messages=False,
        can_manage_topics=False,
    )


def unmuted_permissions() -> ChatPermissions:
    return ChatPermissions(
        can_send_messages=True,
        can_send_audios=True,
        can_send_documents=True,
        can_send_photos=True,
        can_send_videos=True,
        can_send_video_notes=True,
        can_send_voice_notes=True,
        can_send_polls=True,
        can_send_other_messages=True,
        can_add_web_page_previews=True,
        can_change_info=False,
        can_invite_users=True,
        can_pin_messages=False,
        can_manage_topics=True,
    )


async def mute_member(chat, user_id: int, minutes: int, permission_service=None) -> None:
    chat_context = build_chat_context(chat)
    if not chat_context or not chat_context.capabilities.supports_member_restriction:
        raise UnsupportedChatFeature(
            "individual_member_restriction_not_supported_for_basic_group"
        )
    if permission_service is not None:
        await permission_service.require_bot(chat, "restrict_member")
    until_date = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    await chat.restrict_member(
        user_id=user_id,
        permissions=muted_permissions(),
        until_date=until_date,
    )


async def unmute_member(chat, user_id: int, permission_service=None) -> None:
    chat_context = build_chat_context(chat)
    if not chat_context or not chat_context.capabilities.supports_member_restriction:
        raise UnsupportedChatFeature(
            "individual_member_restriction_not_supported_for_basic_group"
        )
    # Restore the current group's defaults instead of blindly granting every
    # permission. Fetch fresh ChatFullInfo when possible so a supergroup that
    # changed its defaults while the user was muted is respected.
    permissions = None
    try:
        policy = getattr(permission_service, "error_policy", None)
        get_chat = chat.get_chat
        chat_info = await (policy.call_read(get_chat, scope_id=int(chat.id)) if policy else get_chat())
        permissions = getattr(chat_info, "permissions", None)
    except Exception as exc:
        raise PermissionLookupError("could_not_restore_current_chat_permissions") from exc
    if permissions is None:
        # Never grant a synthetic broad permission set after a failed Telegram
        # read. H02 requires an authoritative snapshot for restoration.
        raise PermissionLookupError("could_not_restore_current_chat_permissions")
    if permission_service is not None:
        await permission_service.require_bot(chat, "restrict_member")
    await chat.restrict_member(
        user_id=user_id,
        permissions=permissions,
    )


async def ban_member(chat, user_id: int, permission_service=None) -> None:
    chat_context = build_chat_context(chat)
    if not chat_context or not chat_context.capabilities.supports_member_ban:
        raise UnsupportedChatFeature("member_ban_not_supported_for_chat")
    if permission_service is not None:
        await permission_service.require_bot(chat, "ban_member")
    await chat.ban_member(user_id=user_id)


async def unban_member(chat, user_id: int, permission_service=None) -> None:
    chat_context = build_chat_context(chat)
    # Bot API unbanChatMember is available for supergroups/channels; Ghostea
    # only accepts its supported group/supergroup moderation contexts.
    if not chat_context or not chat_context.capabilities.is_supergroup:
        raise UnsupportedChatFeature("member_unban_not_supported_for_chat")
    if permission_service is not None:
        await permission_service.require_bot(chat, "unban_member")
    await chat.unban_member(user_id=user_id, only_if_banned=True)


async def require_message_delete_permission(chat, permission_service=None) -> None:
    chat_context = build_chat_context(chat)
    if not chat_context or not chat_context.capabilities.supports_message_deletion:
        raise UnsupportedChatFeature("message_deletion_not_supported_for_chat")
    # Incoming private-chat messages can be deleted without an admin right;
    # group/supergroup moderation requires the corresponding admin privilege.
    if chat_context.is_private_chat:
        return
    if permission_service is not None:
        await permission_service.require_bot(chat, "delete_message")


async def is_admin(chat, user_id: int, permission_service=None) -> bool:
    if permission_service is not None:
        return await permission_service.is_admin(chat, user_id)
    key = (int(chat.id), int(user_id))
    now = time.monotonic()
    cached = _ADMIN_CACHE.get(key)
    if cached and cached[0] > now:
        return cached[1]
    # Lookup failures intentionally propagate. Callers may treat an unknown
    # admin status as unknown rather than silently granting privilege.
    member = await chat.get_member(user_id)
    value = member.status in (
        ChatMemberStatus.ADMINISTRATOR,
        ChatMemberStatus.OWNER,
    )
    _ADMIN_CACHE[key] = (now + _ADMIN_CACHE_TTL, value)
    return value


async def perform_delete_message(message, chat, permission_service=None) -> ActionResult:
    """Delete a message and return an explicit H03 outcome."""
    try:
        await require_message_delete_permission(chat, permission_service)
    except Exception as error:
        from ghostea.services.action_result import classify_exception
        status, detail, retry_after = classify_exception(error)
        return ActionResult("delete_message", status, detail, retry_after)
    return await execute_action("delete_message", message.delete)


async def perform_mute_member(chat, user_id: int, minutes: int, permission_service=None, requester_id=None) -> ActionResult:
    try:
        await verify_moderation_target(chat, user_id, permission_service, requester_id=requester_id)
        chat_context = build_chat_context(chat)
        if not chat_context or not chat_context.capabilities.supports_member_restriction:
            return ActionResult("restrict_member", ActionStatus.SKIPPED_UNSUPPORTED,
                                 "individual_member_restriction_not_supported_for_basic_group")
        if permission_service is not None:
            await permission_service.require_bot(chat, "restrict_member")
        until_date = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        return await _run_keyed(
            chat.id, user_id,
            lambda: execute_action(
                "restrict_member",
                lambda: chat.restrict_member(user_id=user_id, permissions=muted_permissions(), until_date=until_date),
            ),
        )
    except Exception as error:
        from ghostea.services.action_result import classify_exception
        status, detail, retry_after = classify_exception(error)
        return ActionResult("restrict_member", status, detail, retry_after)


async def perform_unmute_member(chat, user_id: int, permission_service=None, requester_id=None) -> ActionResult:
    try:
        await verify_moderation_target(chat, user_id, permission_service, requester_id=requester_id)
        chat_context = build_chat_context(chat)
        if not chat_context or not chat_context.capabilities.supports_member_restriction:
            return ActionResult("unrestrict_member", ActionStatus.SKIPPED_UNSUPPORTED,
                                 "individual_member_restriction_not_supported_for_basic_group")
        try:
            chat_info = await chat.get_chat()
            permissions = getattr(chat_info, "permissions", None)
        except Exception as error:
            from ghostea.services.action_result import classify_exception
            status, detail, retry_after = classify_exception(error)
            return ActionResult("unrestrict_member", status, detail, retry_after)
        if permissions is None:
            return ActionResult("unrestrict_member", ActionStatus.FAILED_UNKNOWN,
                                 "could_not_restore_current_chat_permissions")
        if permission_service is not None:
            await permission_service.require_bot(chat, "restrict_member")
        return await _run_keyed(
            chat.id, user_id,
            lambda: execute_action(
                "unrestrict_member",
                lambda: chat.restrict_member(user_id=user_id, permissions=permissions),
            ),
        )
    except Exception as error:
        from ghostea.services.action_result import classify_exception
        status, detail, retry_after = classify_exception(error)
        return ActionResult("unrestrict_member", status, detail, retry_after)


async def perform_ban_member(chat, user_id: int, permission_service=None, requester_id=None) -> ActionResult:
    try:
        await verify_moderation_target(chat, user_id, permission_service, requester_id=requester_id)
        chat_context = build_chat_context(chat)
        if not chat_context or not chat_context.capabilities.supports_member_ban:
            return ActionResult("ban_member", ActionStatus.SKIPPED_UNSUPPORTED,
                                 "member_ban_not_supported_for_chat")
        if permission_service is not None:
            await permission_service.require_bot(chat, "ban_member")
        return await _run_keyed(
            chat.id, user_id,
            lambda: execute_action("ban_member", lambda: chat.ban_member(user_id=user_id)),
        )
    except Exception as error:
        from ghostea.services.action_result import classify_exception
        status, detail, retry_after = classify_exception(error)
        return ActionResult("ban_member", status, detail, retry_after)


async def perform_unban_member(chat, user_id: int, permission_service=None, requester_id=None) -> ActionResult:
    try:
        if requester_id is not None and int(user_id) == int(requester_id):
            return ActionResult("unban_member", ActionStatus.SKIPPED_NO_PERMISSION, "target_is_requester")
        chat_context = build_chat_context(chat)
        if not chat_context or not chat_context.capabilities.is_supergroup:
            return ActionResult("unban_member", ActionStatus.SKIPPED_UNSUPPORTED,
                                 "member_unban_not_supported_for_chat")
        if permission_service is not None:
            await permission_service.require_bot(chat, "unban_member")
        return await _run_keyed(
            chat.id, user_id,
            lambda: execute_action(
                "unban_member",
                lambda: chat.unban_member(user_id=user_id, only_if_banned=True),
            ),
        )
    except Exception as error:
        from ghostea.services.action_result import classify_exception
        status, detail, retry_after = classify_exception(error)
        return ActionResult("unban_member", status, detail, retry_after)
