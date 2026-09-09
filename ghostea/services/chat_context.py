"""Canonical Telegram chat/message context for Ghostea Phase 11.

Phase 11 adds canonical chat visibility metadata on top of the existing
Group/Supergroup and forum-topic context model. Normal groups and non-forum supergroups keep a
``None`` topic id; forum messages carry Telegram's ``message_thread_id``.
"""
from dataclasses import dataclass

from ghostea.services.scope_policy import CHAT_WIDE, TOPIC_AWARE, scope_key as resolve_scope_key
from typing import Optional

SUPPORTED_CHAT_TYPES = frozenset({"group", "supergroup"})


@dataclass(frozen=True)
class ChatContext:
    chat_id: int
    chat_type: str
    title: str
    username: Optional[str]
    is_group: bool
    is_supergroup: bool
    is_forum: bool
    topic_id: Optional[int]
    visibility: str = "private"
    # Bot API 9.3+: forum-topic mode can be enabled for private chats.
    private_topics_enabled: bool = False
    # Bot API 9.2+: supergroup-shaped direct-messages chats for channels.
    # These are intentionally outside Ghostea's moderation model.
    is_direct_messages: bool = False

    @property
    def capabilities(self):
        """Return the centralized stable capability set for this context."""
        from ghostea.services.chat_capabilities import resolve_chat_capabilities
        return resolve_chat_capabilities(self)

    @property
    def is_public(self) -> bool:
        """Whether Telegram exposes this group/supergroup with a public username."""
        return self.visibility == "public"

    @property
    def is_private(self) -> bool:
        return self.visibility == "private"

    @property
    def is_private_chat(self) -> bool:
        return self.chat_type == "private"

    @property
    def is_private_topic_message(self) -> bool:
        return self.is_private_chat and self.private_topics_enabled and self.topic_id is not None

    @property
    def is_topic_capable(self) -> bool:
        """Whether this context can carry Telegram forum-topic messages."""
        return self.is_forum or (self.is_private_chat and self.private_topics_enabled)

    @property
    def is_topic_message(self) -> bool:
        """Whether this update has a concrete forum-topic context."""
        return self.is_topic_capable and self.topic_id is not None

    @property
    def has_topics(self) -> bool:
        """Whether the chat is a Telegram forum-capable supergroup."""
        return self.is_topic_capable

    @property
    def scope_key(self):
        """Stable topic-aware scope; topic ids are only unique inside a chat."""
        return resolve_scope_key(self, TOPIC_AWARE)

    @property
    def chat_scope_key(self):
        """Stable chat-wide scope for member/security state."""
        return resolve_scope_key(self, CHAT_WIDE)

    def service_scope_key(self, service_name):
        """Resolve a service's declared scope through the central policy."""
        from ghostea.services.scope_policy import get_service_scope
        return resolve_scope_key(self, get_service_scope(service_name).mode)

    @property
    def is_supported(self) -> bool:
        return self.chat_type in SUPPORTED_CHAT_TYPES

    @property
    def topic_label(self) -> str:
        if self.topic_id is None:
            return "chat"
        return f"topic:{self.topic_id}"


def build_chat_context(chat, message=None, private_topics_enabled=False) -> Optional[ChatContext]:
    """Build one canonical context from a Telegram Chat and optional Message.

    ``message_thread_id`` is deliberately ignored for non-forum chats. This
    prevents malformed/stale thread metadata from accidentally turning a
    normal group into a topic-scoped context.
    """
    if not chat or getattr(chat, "type", None) not in SUPPORTED_CHAT_TYPES and getattr(chat, "type", None) != "private":
        return None

    # Telegram forum topics are a supergroup capability. Private-chat topics
    # are separately enabled for the bot account (Bot API 9.3+).
    # defensive so stale/malformed metadata cannot create a forum context for
    # an ordinary group.
    is_private = chat.type == "private"
    is_forum = chat.type == "supergroup" and bool(getattr(chat, "is_forum", False))
    is_direct_messages = chat.type == "supergroup" and bool(getattr(chat, "is_direct_messages", False))
    private_topics = bool(is_private and private_topics_enabled)
    thread_id = getattr(message, "message_thread_id", None) if message else None
    topic_id = None
    if is_forum:
        # Telegram's General forum topic is the one exception to the normal
        # message_thread_id rule: General messages do not carry a thread id.
        # Treat it as topic id 1 so topic-scoped settings/moderation and the
        # upload topic picker do not accidentally fall back to chat-wide scope.
        if thread_id is None and message is not None:
            topic_id = 1
        else:
            try:
                topic_id = int(thread_id)
            except (TypeError, ValueError, OverflowError):
                # Malformed thread metadata must never create a topic scope.
                topic_id = None
    elif private_topics and thread_id is not None:
        try:
            topic_id = int(thread_id)
        except (TypeError, ValueError, OverflowError):
            topic_id = None

    try:
        chat_id = int(chat.id)
    except (TypeError, ValueError, OverflowError):
        return None

    # For Telegram groups/supergroups, a public username is the stable Bot API
    # signal that the chat is public. Invite-only chats normally have no
    # username. Keep this as a derived visibility field rather than duplicating
    # it as an independent boolean.
    username = getattr(chat, "username", None)
    # Bot API exposes a chat username when available. For groups/supergroups,
    # this is the reliable public-username signal available in the Chat object.
    # Basic groups cannot be assigned a public username by Telegram, so they
    # naturally resolve to private here.
    visibility = "public" if username else "private"

    return ChatContext(
        chat_id=chat_id,
        chat_type=str(chat.type),
        title=str(getattr(chat, "title", None) or ""),
        username=getattr(chat, "username", None),
        is_group=chat.type == "group",
        is_supergroup=chat.type == "supergroup",
        is_forum=is_forum,
        topic_id=topic_id,
        visibility=visibility,
        private_topics_enabled=private_topics,
        is_direct_messages=is_direct_messages,
    )


def is_supported_chat(chat) -> bool:
    return bool(chat and getattr(chat, "type", None) in SUPPORTED_CHAT_TYPES)


def build_update_context(update, private_topics_enabled=False) -> Optional[ChatContext]:
    """Resolve the canonical context directly from a python-telegram-bot Update."""
    if not update:
        return None
    return build_chat_context(
        getattr(update, "effective_chat", None),
        getattr(update, "effective_message", None),
        private_topics_enabled=private_topics_enabled,
    )



def build_update_capabilities(update, private_topics_enabled=False):
    """Resolve chat capabilities from a Telegram Update without I/O."""
    context = build_update_context(update, private_topics_enabled=private_topics_enabled)
    if context is None:
        return None
    return context.capabilities
