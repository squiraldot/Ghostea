"""Phase 17 — public/private chat behaviour.

Visibility is an identity/UX property, not a moderation capability. Telegram
exposes a public username for public groups/supergroups; private chats/groups
do not have a public username. This service keeps that distinction centralized
and prevents callers from manufacturing public links for private chats.
"""

from dataclasses import dataclass
from typing import Optional

from ghostea.services.chat_context import ChatContext


@dataclass(frozen=True)
class ChatVisibility:
    visibility: str
    username: Optional[str]
    public_url: Optional[str]
    access_label: str
    is_public: bool
    is_private: bool
    can_show_public_link: bool

    @property
    def identity_label(self) -> str:
        if self.is_public and self.username:
            return f"@{self.username}"
        return "Private chat"

    def as_dict(self) -> dict:
        return {
            "visibility": self.visibility,
            "username": self.username,
            "public_url": self.public_url,
            "access_label": self.access_label,
            "is_public": self.is_public,
            "is_private": self.is_private,
            "can_show_public_link": self.can_show_public_link,
            "identity_label": self.identity_label,
        }


def _clean_username(username):
    value = str(username or "").strip().lstrip("@")
    return value or None


def resolve_chat_visibility(context: Optional[ChatContext]) -> ChatVisibility:
    """Resolve public/private presentation from canonical chat context.

    Basic groups are always treated as private because Telegram does not give
    them native public usernames. For supported supergroups the username is
    the public-identity signal already used by ChatContext.
    """
    if context is None or not context.is_supported:
        return ChatVisibility(
            "private", None, None, "Unsupported/private", False, True, False
        )

    username = _clean_username(context.username)
    is_public = bool(
        context.is_supergroup and username and context.visibility == "public"
    )

    if is_public:
        return ChatVisibility(
            visibility="public",
            username=username,
            public_url=f"https://t.me/{username}",
            access_label="Public username",
            is_public=True,
            is_private=False,
            can_show_public_link=True,
        )

    return ChatVisibility(
        visibility="private",
        username=None,
        public_url=None,
        access_label="Private / no public username",
        is_public=False,
        is_private=True,
        can_show_public_link=False,
    )


def visibility_from_registry(row) -> ChatVisibility:
    """Resolve dashboard-safe visibility from persisted registry metadata.

    Username is normalized and only a supergroup can become publicly
    addressable. Stale `visibility=public` on a basic group is ignored.
    """
    if not isinstance(row, dict):
        return resolve_chat_visibility(None)

    chat_type = str(row.get("chat_type") or "")
    username = _clean_username(row.get("username"))
    visibility = str(row.get("visibility") or "private")

    if chat_type == "supergroup" and visibility == "public" and username:
        return ChatVisibility(
            "public", username, f"https://t.me/{username}",
            "Public username", True, False, True
        )

    return ChatVisibility(
        "private", None, None, "Private / no public username",
        False, True, False
    )
