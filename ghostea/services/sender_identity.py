"""Phase H06 — Telegram sender/member identity classification.

The moderation system must never infer a human member identity from a
sender-chat context. Telegram can represent anonymous administrators,
channels, and other chat-backed senders through ``sender_chat``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class SenderIdentity:
    """Conservative identity view of a Telegram message sender."""
    user: Optional[Any]
    sender_chat: Optional[Any]
    kind: str
    user_id: Optional[int]
    is_human_user: bool
    is_chat_sender: bool
    is_anonymous_or_unknown: bool
    can_be_moderation_target: bool

    @property
    def is_bot(self) -> bool:
        return bool(self.user is not None and getattr(self.user, "is_bot", False))

    @property
    def chat_id(self) -> Optional[int]:
        value = getattr(self.sender_chat, "id", None)
        return int(value) if value is not None else None


def classify_sender(message: Any) -> SenderIdentity:
    user = getattr(message, "from_user", None)
    sender_chat = getattr(message, "sender_chat", None)

    if sender_chat is not None:
        # A sender_chat represents a chat-backed sender. Even if Telegram also
        # exposes a user object, do not guess that the user is the actual
        # moderation subject for this message.
        kind = "anonymous_admin_or_chat_sender"
        return SenderIdentity(
            user=user,
            sender_chat=sender_chat,
            kind=kind,
            user_id=None,
            is_human_user=False,
            is_chat_sender=True,
            is_anonymous_or_unknown=True,
            can_be_moderation_target=False,
        )

    if user is None:
        return SenderIdentity(
            user=None, sender_chat=None, kind="unknown", user_id=None,
            is_human_user=False, is_chat_sender=False,
            is_anonymous_or_unknown=True, can_be_moderation_target=False,
        )

    user_id = getattr(user, "id", None)
    if user_id is None:
        return SenderIdentity(
            user=user, sender_chat=None, kind="unknown", user_id=None,
            is_human_user=False, is_chat_sender=False,
            is_anonymous_or_unknown=True, can_be_moderation_target=False,
        )

    if bool(getattr(user, "is_bot", False)):
        kind = "bot"
    else:
        kind = "user"
    return SenderIdentity(
        user=user, sender_chat=None, kind=kind, user_id=int(user_id),
        is_human_user=not bool(getattr(user, "is_bot", False)),
        is_chat_sender=False, is_anonymous_or_unknown=False,
        # Existing Ghostea moderation targets human members only.
        can_be_moderation_target=not bool(getattr(user, "is_bot", False)),
    )


def moderation_sender(message: Any) -> Optional[Any]:
    """Return a safe human moderation target, never a sender-chat identity."""
    identity = classify_sender(message)
    return identity.user if identity.can_be_moderation_target else None
