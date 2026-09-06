"""Phase H01 — Telegram Bot API compatibility contract.

This module is a dependency-light, explicit snapshot of the Telegram Bot API
surface that Ghostea relies on.  It is deliberately descriptive: it does not
perform network calls and does not turn API support into live bot permission.

The current project targets python-telegram-bot 22.x and the Telegram Bot API
10.3 contract documented on 2026-08-24.  Keep this module synchronized when
Telegram adds/removes fields or methods.
"""

from dataclasses import dataclass
from typing import FrozenSet, Mapping


TELEGRAM_BOT_API_BASELINE = "10.3"
PTB_MAJOR = 22

SUPPORTED_CHAT_TYPES: FrozenSet[str] = frozenset(
    {"group", "supergroup", "private", "channel"}
)

GHOSTEA_MODERATION_CHAT_TYPES: FrozenSet[str] = frozenset(
    {"group", "supergroup"}
)

MESSAGE_UPDATE_TYPES: FrozenSet[str] = frozenset(
    {
        "message",
        "edited_message",
        "channel_post",
        "edited_channel_post",
    }
)

MEMBERSHIP_UPDATE_TYPES: FrozenSet[str] = frozenset(
    {"chat_member", "my_chat_member", "chat_join_request"}
)

OTHER_UPDATE_TYPES: FrozenSet[str] = frozenset(
    {
        "inline_query",
        "chosen_inline_result",
        "callback_query",
        "shipping_query",
        "pre_checkout_query",
        "poll",
        "poll_answer",
        "my_chat_member",
        "chat_member",
        "chat_join_request",
        "chat_boost",
        "removed_chat_boost",
        "message_reaction",
        "message_reaction_count",
        "business_connection",
        "business_message",
        "edited_business_message",
        "deleted_business_messages",
        "purchased_paid_media",
        "paid_media_purchased",
        "direct_message_price_changed",
        "direct_messages_topic",
        "direct_messages_topic_deleted",
    }
)

# ChatPermissions fields documented by Telegram Bot API 10.3. Keeping this
# list explicit prevents mute/unmute code from silently omitting new fields.
CHAT_PERMISSION_FIELDS: tuple[str, ...] = (
    "can_send_messages",
    "can_send_audios",
    "can_send_documents",
    "can_send_photos",
    "can_send_videos",
    "can_send_video_notes",
    "can_send_voice_notes",
    "can_send_polls",
    "can_send_other_messages",
    "can_add_web_page_previews",
    "can_change_info",
    "can_invite_users",
    "can_pin_messages",
    "can_manage_topics",
    "can_react_to_messages",
    "can_edit_tag",
)

# Administrator rights Ghostea may need.  can_restrict_members covers
# restrict/ban/unban operations according to Telegram's Bot API.
ADMIN_PERMISSION_FIELDS: tuple[str, ...] = (
    "can_manage_chat",
    "can_delete_messages",
    "can_manage_video_chats",
    "can_restrict_members",
    "can_promote_members",
    "can_change_info",
    "can_invite_users",
    "can_post_stories",
    "can_edit_stories",
    "can_delete_stories",
    "can_post_messages",
    "can_edit_messages",
    "can_pin_messages",
    "can_manage_topics",
    "can_manage_direct_messages",
    "can_manage_tags",
)

FORUM_TOPIC_METHODS: FrozenSet[str] = frozenset(
    {
        "createForumTopic",
        "editForumTopic",
        "closeForumTopic",
        "reopenForumTopic",
        "deleteForumTopic",
        "unpinAllForumTopicMessages",
        "getForumTopicIconStickers",
        "hideGeneralForumTopic",
        "unhideGeneralForumTopic",
        "unpinAllGeneralForumTopicMessages",
    }
)

PRIVATE_TOPIC_METHODS: FrozenSet[str] = frozenset(
    {
        "createForumTopic",
        "editForumTopic",
        "deleteForumTopic",
        "unpinAllForumTopicMessages",
    }
)

# Telegram documents that these operations are available in groups/supergroups
# with the relevant rights.  This is a contract map, not a permission grant.
OPERATION_CONTRACTS: Mapping[str, Mapping[str, object]] = {
    "delete_message": {
        "methods": ("deleteMessage",),
        "chat_types": ("group", "supergroup"),
        "required_admin_right": "can_delete_messages",
        "notable_limit": "message_deletion_window",
    },
    "restrict_member": {
        "methods": ("restrictChatMember",),
        "chat_types": ("supergroup",),
        "required_admin_right": "can_restrict_members",
    },
    "ban_member": {
        "methods": ("banChatMember",),
        "chat_types": ("group", "supergroup"),
        "required_admin_right": "can_restrict_members",
    },
    "unban_member": {
        "methods": ("unbanChatMember",),
        "chat_types": ("supergroup",),
        "required_admin_right": "can_restrict_members",
    },
    "set_default_permissions": {
        "methods": ("setChatPermissions",),
        "chat_types": ("group", "supergroup"),
        "required_admin_right": "can_restrict_members",
        "notable_limit": "independent_chat_permissions",
    },
    "create_forum_topic": {
        "methods": ("createForumTopic",),
        "chat_types": ("supergroup", "private"),
        "required_admin_right": "can_manage_topics",
        "private_bot_flag": "has_topics_enabled",
        "private_required_admin_right": None,
    },
    "edit_forum_topic": {
        "methods": ("editForumTopic",),
        "chat_types": ("supergroup", "private"),
        "required_admin_right": "can_manage_topics",
        "private_required_admin_right": None,
        "private_bot_flag": "has_topics_enabled",
    },
    "close_forum_topic": {
        "methods": ("closeForumTopic",),
        "chat_types": ("supergroup",),
        "required_admin_right": "can_manage_topics",
    },
    "reopen_forum_topic": {
        "methods": ("reopenForumTopic",),
        "chat_types": ("supergroup",),
        "required_admin_right": "can_manage_topics",
    },
    "delete_forum_topic": {
        "methods": ("deleteForumTopic",),
        "chat_types": ("supergroup", "private"),
        # In a supergroup Telegram requires can_delete_messages for this
        # operation; private chats have no administrator-right requirement.
        "required_admin_right": "can_delete_messages",
        "private_bot_flag": "has_topics_enabled",
    },
}


@dataclass(frozen=True)
class TelegramContract:
    """Immutable API contract metadata exposed to diagnostics/tests."""

    bot_api_baseline: str = TELEGRAM_BOT_API_BASELINE
    ptb_major: int = PTB_MAJOR
    chat_permission_fields: tuple[str, ...] = CHAT_PERMISSION_FIELDS
    admin_permission_fields: tuple[str, ...] = ADMIN_PERMISSION_FIELDS
    message_update_types: FrozenSet[str] = MESSAGE_UPDATE_TYPES
    membership_update_types: FrozenSet[str] = MEMBERSHIP_UPDATE_TYPES

    def operation(self, name: str) -> Mapping[str, object]:
        try:
            return OPERATION_CONTRACTS[name]
        except KeyError as exc:
            raise KeyError(f"Unknown Telegram operation contract: {name}") from exc

    def as_dict(self) -> dict:
        return {
            "bot_api_baseline": self.bot_api_baseline,
            "ptb_major": self.ptb_major,
            "chat_permission_fields": list(self.chat_permission_fields),
            "admin_permission_fields": list(self.admin_permission_fields),
            "message_update_types": sorted(self.message_update_types),
            "membership_update_types": sorted(self.membership_update_types),
            "forum_topic_methods": sorted(FORUM_TOPIC_METHODS),
            "private_topic_methods": sorted(PRIVATE_TOPIC_METHODS),
            "operation_contracts": {
                key: dict(value) for key, value in OPERATION_CONTRACTS.items()
            },
        }


TELEGRAM_CONTRACT = TelegramContract()


def validate_chat_type(chat_type: str) -> bool:
    return str(chat_type or "") in SUPPORTED_CHAT_TYPES


def validate_permission_mapping(values: Mapping[str, object]) -> bool:
    """Return True only when a permission mapping uses known Bot API fields."""
    return all(key in CHAT_PERMISSION_FIELDS for key in values)


def validate_update_type(update_type: str) -> bool:
    """Recognize documented update families without treating them as handled."""
    return (
        update_type in MESSAGE_UPDATE_TYPES
        or update_type in MEMBERSHIP_UPDATE_TYPES
        or update_type in OTHER_UPDATE_TYPES
    )


def contract_summary() -> dict:
    """Small stable payload for readiness/diagnostic endpoints."""
    return {
        "bot_api_baseline": TELEGRAM_BOT_API_BASELINE,
        "ptb_major": PTB_MAJOR,
        "chat_types": sorted(SUPPORTED_CHAT_TYPES),
        "ghostea_moderation_chat_types": sorted(GHOSTEA_MODERATION_CHAT_TYPES),
        "chat_permission_fields": list(CHAT_PERMISSION_FIELDS),
        "admin_permission_fields": list(ADMIN_PERMISSION_FIELDS),
        "message_update_types": sorted(MESSAGE_UPDATE_TYPES),
        "membership_update_types": sorted(MEMBERSHIP_UPDATE_TYPES),
    }
