"""Phase H13 — canonical Telegram compatibility matrix.

This module is deliberately declarative.  It answers two separate questions:
1. what the Telegram Bot API supports for a chat/update shape, and
2. whether Ghostea intentionally supports that shape without making live API
   calls.

It does not grant permissions and it never performs network I/O.
"""
from dataclasses import dataclass
from typing import FrozenSet, Mapping

from ghostea.services.chat_context import ChatContext
from ghostea.services.chat_capabilities import resolve_chat_capabilities
from ghostea.services.telegram_contract import OPERATION_CONTRACTS, validate_update_type


H13_OPERATIONS: FrozenSet[str] = frozenset(
    {
        "delete_message",
        "restrict_member",
        "ban_member",
        "unban_member",
        "set_default_permissions",
        "create_forum_topic",
        "edit_forum_topic",
        "close_forum_topic",
        "reopen_forum_topic",
        "delete_forum_topic",
    }
)

# Telegram currently exposes these update fields.  Ghostea only acts on a
# subset; the rest must be ignored safely rather than interpreted as messages.
TELEGRAM_UPDATE_SHAPES: FrozenSet[str] = frozenset(
    {
        "message",
        "edited_message",
        "channel_post",
        "edited_channel_post",
        "business_connection",
        "business_message",
        "edited_business_message",
        "deleted_business_messages",
        "guest_message",
        "message_reaction",
        "message_reaction_count",
        "inline_query",
        "chosen_inline_result",
        "callback_query",
        "shipping_query",
        "pre_checkout_query",
        "purchased_paid_media",
        "poll",
        "poll_answer",
        "my_chat_member",
        "chat_member",
        "chat_join_request",
        "chat_boost",
        "removed_chat_boost",
        "managed_bot",
        "subscription",
        "stopped_message_generation",
    }
)

GHOSTEA_HANDLED_UPDATE_SHAPES: FrozenSet[str] = frozenset(
    {"message", "edited_message", "my_chat_member", "chat_member"}
)


@dataclass(frozen=True)
class CompatibilityCase:
    name: str
    chat_type: str
    visibility: str
    is_forum: bool = False
    private_topics_enabled: bool = False
    is_direct_messages: bool = False

    def context(self, topic_id=42):
        topic = topic_id if (
            (self.chat_type == "supergroup" and self.is_forum)
            or (self.chat_type == "private" and self.private_topics_enabled)
        ) else None
        return ChatContext(
            chat_id=1,
            chat_type=self.chat_type,
            title=self.name,
            username=("example" if self.visibility == "public" and self.chat_type == "supergroup" else None),
            is_group=self.chat_type == "group",
            is_supergroup=self.chat_type == "supergroup",
            is_forum=self.is_forum,
            topic_id=topic,
            visibility=self.visibility,
            private_topics_enabled=self.private_topics_enabled,
            is_direct_messages=self.is_direct_messages,
        )


CASES = (
    CompatibilityCase("basic_group_private", "group", "private"),
    CompatibilityCase("supergroup_private", "supergroup", "private"),
    CompatibilityCase("supergroup_public", "supergroup", "public"),
    CompatibilityCase("forum_private", "supergroup", "private", True),
    CompatibilityCase("forum_public", "supergroup", "public", True),
    CompatibilityCase("private_chat_topics_disabled", "private", "private"),
    CompatibilityCase("private_chat_topics_enabled", "private", "private", private_topics_enabled=True),
    # Channel direct-message chats are represented as supergroups by Bot API,
    # but are a distinct chat role and are intentionally outside Ghostea's
    # moderation model.  H13 must fail closed rather than treating them as a
    # normal supergroup/forum.
    CompatibilityCase("channel_direct_messages", "supergroup", "private", is_direct_messages=True),
    CompatibilityCase("channel_unsupported", "channel", "public"),
)


def _operation_supported(caps, operation: str) -> bool:
    """Stable platform/chat-shape support, excluding live permissions."""
    if operation == "delete_message":
        return caps.supports_message_deletion
    if operation == "restrict_member":
        return caps.supports_member_restriction
    if operation == "ban_member":
        return caps.supports_member_ban
    if operation == "unban_member":
        return caps.supports_member_unban
    if operation == "set_default_permissions":
        return caps.supports_default_permissions
    if operation in {"create_forum_topic", "edit_forum_topic", "close_forum_topic", "reopen_forum_topic", "delete_forum_topic"}:
        if caps.chat_type == "private":
            return operation in {"create_forum_topic", "edit_forum_topic", "delete_forum_topic"}
        return caps.allows_feature({
            "create_forum_topic": "topic_creation",
            "edit_forum_topic": "topic_management",
            "close_forum_topic": "topic_management",
            "reopen_forum_topic": "topic_management",
            "delete_forum_topic": "topic_deletion",
        }[operation])
    raise KeyError(operation)


def build_matrix():
    result = []
    for case in CASES:
        ctx = case.context()
        caps = resolve_chat_capabilities(ctx)
        operations = {}
        for operation in sorted(H13_OPERATIONS):
            contract = OPERATION_CONTRACTS.get(operation)
            operations[operation] = {
                "supported_by_ghostea": bool(_operation_supported(caps, operation)),
                "required_admin_right": contract.get("required_admin_right") if contract else None,
                "chat_types": list(contract.get("chat_types", ())) if contract else [],
                "requires_live_permission": bool(contract and contract.get("required_admin_right")),
            }
        result.append({
            "name": case.name,
            "kind": caps.kind,
            "chat_type": case.chat_type,
            "visibility": case.visibility,
            "is_forum": case.is_forum,
            "is_direct_messages": case.is_direct_messages,
            "private_topics_enabled": case.private_topics_enabled,
            "supports_moderation": caps.supports_member_moderation,
            "supports_message_deletion": caps.supports_message_deletion,
            "supports_restriction": caps.supports_member_restriction,
            "supports_bans": caps.supports_member_ban,
            "supports_unbans": caps.supports_member_unban,
            "supports_default_permissions": caps.supports_default_permissions,
            "supports_topics": caps.supports_topics,
            "supports_topic_messages": caps.supports_forum_topic_messages,
            "topic_messages": caps.supports_forum_topic_messages,
            "operations": operations,
        })
    return result


def validate_matrix(matrix=None):
    """Return deterministic validation errors for the H13 compatibility table."""
    matrix = list(matrix if matrix is not None else build_matrix())
    errors = []
    by_name = {row["name"]: row for row in matrix}
    if set(by_name) != {case.name for case in CASES}:
        errors.append("matrix_case_set_mismatch")
    for row in matrix:
        if row["kind"] == "group":
            if row["supports_restriction"] or row["supports_unbans"]:
                errors.append(f"basic_group_restriction_or_unban:{row['name']}")
        if row["is_direct_messages"] and row["supports_moderation"]:
            errors.append(f"direct_messages_moderation_enabled:{row['name']}")
        if row["kind"] == "forum_supergroup" and not row["supports_topics"]:
            errors.append(f"forum_without_topics:{row['name']}")
        if row["kind"] != "forum_supergroup" and row["chat_type"] != "private" and row["supports_topic_messages"]:
            errors.append(f"non_forum_topic_messages:{row['name']}")
    for update_type in TELEGRAM_UPDATE_SHAPES:
        if not validate_update_type(update_type) and update_type not in {"managed_bot", "subscription", "guest_message"}:
            errors.append(f"unknown_update_contract:{update_type}")
    return errors


def matrix_summary():
    matrix = build_matrix()
    return {
        "cases": matrix,
        "case_count": len(matrix),
        "operations": sorted(H13_OPERATIONS),
        "telegram_update_shapes": sorted(TELEGRAM_UPDATE_SHAPES),
        "ghostea_handled_update_shapes": sorted(GHOSTEA_HANDLED_UPDATE_SHAPES),
        "valid": not validate_matrix(matrix),
        "validation_errors": validate_matrix(matrix),
    }
