from datetime import datetime, timedelta, timezone

from telegram import ChatPermissions
from telegram.constants import ChatMemberStatus

from ghostea.services.chat_context import build_chat_context


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


async def mute_member(chat, user_id: int, minutes: int) -> None:
    chat_context = build_chat_context(chat)
    if not chat_context or not chat_context.capabilities.supports_member_restriction:
        raise UnsupportedChatFeature(
            "individual_member_restriction_not_supported_for_basic_group"
        )
    until_date = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    await chat.restrict_member(
        user_id=user_id,
        permissions=muted_permissions(),
        until_date=until_date,
    )


async def unmute_member(chat, user_id: int) -> None:
    chat_context = build_chat_context(chat)
    if not chat_context or not chat_context.capabilities.supports_member_restriction:
        raise UnsupportedChatFeature(
            "individual_member_restriction_not_supported_for_basic_group"
        )
    # Restore the current group's defaults instead of blindly granting every
    # permission. Fetch fresh ChatFullInfo when possible so a supergroup that
    # changed its defaults while the user was muted is respected.
    permissions = getattr(chat, "permissions", None)
    try:
        chat_info = await chat.get_chat()
        permissions = getattr(chat_info, "permissions", None) or permissions
    except Exception:
        # The restriction itself may still succeed with the cached Chat object.
        pass
    permissions = permissions or unmuted_permissions()
    await chat.restrict_member(
        user_id=user_id,
        permissions=permissions,
    )


async def ban_member(chat, user_id: int) -> None:
    chat_context = build_chat_context(chat)
    if not chat_context or not chat_context.capabilities.supports_member_ban:
        raise UnsupportedChatFeature("member_ban_not_supported_for_chat")
    await chat.ban_member(user_id=user_id)


async def unban_member(chat, user_id: int) -> None:
    chat_context = build_chat_context(chat)
    # Bot API unbanChatMember is available for supergroups/channels; Ghostea
    # only accepts its supported group/supergroup moderation contexts.
    if not chat_context or not chat_context.capabilities.supports_member_ban:
        raise UnsupportedChatFeature("member_unban_not_supported_for_chat")
    await chat.unban_member(user_id=user_id, only_if_banned=True)


async def is_admin(chat, user_id: int) -> bool:
    member = await chat.get_member(user_id)
    return member.status in (
        ChatMemberStatus.ADMINISTRATOR,
        ChatMemberStatus.OWNER,
    )
