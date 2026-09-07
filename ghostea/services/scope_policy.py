"""Central scope policy for Ghostea services.

Phase 7 audits every existing service and makes its data/action scope explicit.
The important distinction is between *member/chat state* (chat-wide) and
*message/event context* (optionally topic-aware).
"""
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ServiceScope:
    name: str
    mode: str
    reason: str


CHAT_WIDE = "chat_wide"
TOPIC_AWARE = "topic_aware"
FORUM_ONLY = "forum_only"


SERVICE_SCOPES = {
    # Member/security state must not reset or split when a user changes topics.
    "warnings": ServiceScope("warnings", CHAT_WIDE, "warning state belongs to the whole chat"),
    "reputation": ServiceScope("reputation", CHAT_WIDE, "reputation is member state"),
    "verification": ServiceScope("verification", CHAT_WIDE, "verification is a chat membership gate"),
    "anti_raid": ServiceScope("anti_raid", CHAT_WIDE, "join bursts and default permissions are chat-wide"),
    "welcome": ServiceScope("welcome", CHAT_WIDE, "new-member lifecycle is chat-wide"),
    "user_management": ServiceScope("user_management", CHAT_WIDE, "moderation targets are members of a chat"),
    "rbac": ServiceScope("rbac", CHAT_WIDE, "dashboard roles are chat/admin scoped"),
    "security_locks": ServiceScope("security_locks", CHAT_WIDE, "default chat permissions are chat-wide"),
    "custom_filters": ServiceScope("custom_filters", CHAT_WIDE, "filter definitions are shared by the chat"),
    "settings": ServiceScope("settings", CHAT_WIDE, "group settings are the inheritance base"),
    "joins": ServiceScope("joins", CHAT_WIDE, "join events are chat membership events"),

    # Message-derived telemetry can be narrowed to one forum topic.
    "moderation": ServiceScope("moderation", TOPIC_AWARE, "content decisions use the effective topic settings"),
    "flood": ServiceScope("flood", TOPIC_AWARE, "frequency state is isolated by (chat_id, topic_id)"),
    "repeat_spam": ServiceScope("repeat_spam", TOPIC_AWARE, "repeat state is isolated by message topic"),
    "moderation_logs": ServiceScope("moderation_logs", TOPIC_AWARE, "events retain their originating topic"),
    "analytics": ServiceScope("analytics", TOPIC_AWARE, "event analytics can be filtered by topic"),
    "risk": ServiceScope("risk", TOPIC_AWARE, "event-derived risk can be filtered by topic"),
    "topic_registry": ServiceScope("topic_registry", FORUM_ONLY, "topic metadata exists only for forum supergroups"),
}


def get_service_scope(name: str) -> ServiceScope:
    """Return the declared scope for a Ghostea service."""
    try:
        return SERVICE_SCOPES[name]
    except KeyError:
        raise KeyError(f"unknown Ghostea service scope: {name}")


def normalize_topic_id(chat_context, topic_id: Optional[int] = None):
    """Return a safe topic id for a context, or None outside forum topics.

    A topic id is never meaningful without both its chat id and a forum-capable
    chat context. This prevents callers from accidentally treating a numeric
    topic id as globally unique or applying topic behaviour to normal groups.
    """
    if not chat_context or not chat_context.is_topic_capable:
        return None
    value = topic_id if topic_id is not None else chat_context.topic_id
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def scope_key(chat_context, mode=TOPIC_AWARE):
    """Resolve the canonical state key for a service."""
    if not chat_context:
        return None
    if mode == CHAT_WIDE:
        return (int(chat_context.chat_id), None)
    if mode == FORUM_ONLY and not chat_context.is_forum:
        return None
    topic_id = normalize_topic_id(chat_context)
    return (int(chat_context.chat_id), topic_id)


def audit_snapshot():
    """Small serializable description used by diagnostics/tests."""
    return {
        name: {"mode": item.mode, "reason": item.reason}
        for name, item in SERVICE_SCOPES.items()
    }
