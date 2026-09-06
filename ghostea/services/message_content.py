"""Phase H04 — Telegram message update/content classification.

Dependency-light helpers used by both normal and edited-message handlers.
They deliberately extract only content the existing moderation engine
understands (text/caption) and classify other Telegram message payloads.
"""

from __future__ import annotations


def message_update_kind(update) -> str:
    """Return the Telegram message-update family handled by Ghostea."""
    if getattr(update, "edited_message", None) is not None:
        return "edited_message"
    if getattr(update, "message", None) is not None:
        return "message"
    return "other"


def extract_message_content(message) -> tuple[str, str]:
    """Extract moderation-visible content and a stable content classification."""
    text = getattr(message, "text", None)
    if text:
        return str(text), "text"
    caption = getattr(message, "caption", None)
    if caption:
        return str(caption), "caption"

    for field in (
        "photo", "video", "document", "audio", "voice", "animation",
        "video_note", "sticker", "poll", "dice", "location", "venue",
        "contact", "new_chat_members", "left_chat_member", "new_chat_title",
        "delete_chat_photo", "group_chat_created", "supergroup_chat_created",
        "migrate_to_chat_id", "migrate_from_chat_id", "forum_topic_created",
        "forum_topic_closed", "forum_topic_reopened", "forum_topic_edited",
        "general_forum_topic_hidden", "general_forum_topic_unhidden",
    ):
        if getattr(message, field, None) is not None:
            return "", f"service_or_{field}"
    return "", "non_text"


def is_command_message(message) -> bool:
    """Keep command messages outside the moderation content pipeline."""
    entities = list(getattr(message, "entities", None) or [])
    caption_entities = list(getattr(message, "caption_entities", None) or [])
    return any(
        getattr(entity, "type", None) == "bot_command"
        for entity in entities + caption_entities
    )
