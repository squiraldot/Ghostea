"""Phase 16 topic-aware outbound messaging helpers.

Automated moderation notices must stay in the originating forum topic instead
of silently leaking into the General topic. General topic uses Telegram's
default destination and does not need an explicit thread id.
"""


async def send_in_context(chat, text, topic_id=None, private_topics_enabled=False, **kwargs):
    """Send a bot message to the originating forum topic when applicable."""
    topic_id = int(topic_id) if topic_id is not None else None
    if topic_id is not None and ((getattr(chat, "is_forum", False) and topic_id != 1) or (getattr(chat, "type", None) == "private" and private_topics_enabled)):
        kwargs["message_thread_id"] = topic_id
    return await chat.send_message(text, **kwargs)
