"""Phase 15 — Forum Supergroup Engine.

Centralizes Telegram forum-topic operations and their safety boundaries.
Topic lifecycle state is persisted separately from chat-wide moderation state.
"""
import logging
import secrets

from ghostea.services.chat_capabilities import (
    resolve_chat_capabilities,
    resolve_forum_compatibility,
    resolve_private_chat_topic_compatibility,
    resolve_bot_permissions,
)

logger = logging.getLogger("Ghostea")

GENERAL_TOPIC_ID = 1
MAX_TOPIC_TITLE_LENGTH = 128


class ForumTopicError(RuntimeError):
    """Expected, user-facing forum operation failure."""


class ForumTopicService:
    def __init__(self, store, bot):
        self.store = store
        self.bot = bot

    async def _private_topics_enabled(self):
        try:
            me = await self.bot.get_me()
            return bool(getattr(me, "has_topics_enabled", False))
        except Exception as exc:
            logger.exception("Private topic capability lookup failed")
            raise ForumTopicError("Could not verify Ghostea private-chat topic mode.") from exc

    async def _context(self, chat):
        from ghostea.services.chat_context import build_chat_context
        private_enabled = await self._private_topics_enabled() if getattr(chat, "type", None) == "private" else False
        context = build_chat_context(chat, private_topics_enabled=private_enabled)
        caps = resolve_chat_capabilities(context)

        if getattr(chat, "type", None) == "private":
            profile = resolve_private_chat_topic_compatibility(context)
            if not profile.is_supported:
                raise ForumTopicError(
                    "Private-chat topics are disabled for Ghostea. Enable forum topic mode for this bot in BotFather."
                )
            return context, caps, profile

        profile = resolve_forum_compatibility(caps)
        if not profile.is_supported:
            raise ForumTopicError(
                "Forum topics are available only in Telegram forum supergroups or private chats with topic mode enabled."
            )
        return context, caps, profile

    async def _require_manage_topics(self, chat):
        context, caps, profile = await self._context(chat)
        if getattr(chat, "type", None) == "private":
            return context, caps, profile

        try:
            me = await self.bot.get_me()
            permissions = await resolve_bot_permissions(chat, me.id)
        except Exception as exc:
            logger.exception("Forum permission lookup failed")
            raise ForumTopicError("Could not verify the bot's topic-management permission.") from exc
        if not permissions.is_admin or not permissions.can_manage_topics:
            raise ForumTopicError("Ghostea needs the Manage Topics admin permission in this forum.")
        return context, caps, profile

    @staticmethod
    def _validate_topic_id(topic_id):
        try:
            value = int(topic_id)
        except (TypeError, ValueError):
            raise ForumTopicError("Invalid topic ID.")
        if value < 1:
            raise ForumTopicError("Invalid topic ID.")
        return value

    @staticmethod
    def _validate_title(title):
        title = str(title or "").strip()
        if not title:
            raise ForumTopicError("Topic name cannot be empty.")
        if len(title) > MAX_TOPIC_TITLE_LENGTH:
            raise ForumTopicError("Topic name must be 128 characters or fewer.")
        return title

    @staticmethod
    def topic_id_from_update(update, private_topics_enabled=False):
        from ghostea.services.chat_context import build_chat_context
        ctx = build_chat_context(update.effective_chat, update.effective_message, private_topics_enabled=private_topics_enabled)
        return ctx.topic_id if ctx else None

    async def list_topics(self, chat, include_inactive=False, limit=200):
        await self._context(chat)
        return await self.store.list_topics(
            chat.id, include_inactive=include_inactive, limit=limit
        )

    async def create_topic(self, chat, title, icon_color=None, icon_custom_emoji_id=None):
        await self._require_manage_topics(chat)
        title = self._validate_title(title)
        kwargs = {"chat_id": chat.id, "name": title}
        if icon_color is not None:
            kwargs["icon_color"] = int(icon_color)
        if icon_custom_emoji_id:
            kwargs["icon_custom_emoji_id"] = str(icon_custom_emoji_id)

        topic = await self.bot.create_forum_topic(**kwargs)
        topic_id = int(getattr(topic, "message_thread_id", 0) or 0)
        if not topic_id:
            raise ForumTopicError("Telegram created the topic but returned no topic ID.")

        await self.store.upsert_topic_lifecycle(
            chat.id, topic_id, name=getattr(topic, "name", title),
            is_active=True, is_closed=False
        )
        return topic

    async def rename_topic(self, chat, topic_id, title):
        await self._require_manage_topics(chat)
        topic_id = self._validate_topic_id(topic_id)
        title = self._validate_title(title)
        if topic_id == GENERAL_TOPIC_ID and getattr(chat, "type", None) != "private":
            await self.bot.edit_general_forum_topic(chat_id=chat.id, name=title)
        else:
            await self.bot.edit_forum_topic(
                chat_id=chat.id, message_thread_id=topic_id, name=title
            )
        await self.store.upsert_topic_lifecycle(
            chat.id, topic_id, name=title, is_active=True, is_closed=False
        )
        return True

    async def close_topic(self, chat, topic_id):
        context, caps, profile = await self._require_manage_topics(chat)
        if getattr(chat, "type", None) == "private":
            raise ForumTopicError("Closing topics is not available in private chats through the Telegram Bot API.")
        topic_id = self._validate_topic_id(topic_id)
        if topic_id == GENERAL_TOPIC_ID and getattr(chat, "type", None) != "private":
            await self.bot.close_general_forum_topic(chat_id=chat.id)
        else:
            await self.bot.close_forum_topic(
                chat_id=chat.id, message_thread_id=topic_id
            )
        current = await self.store.get_topic(chat.id, topic_id)
        await self.store.upsert_topic_lifecycle(
            chat.id, topic_id, name=(current or {}).get("name"),
            is_active=True, is_closed=True
        )
        return True

    async def reopen_topic(self, chat, topic_id):
        context, caps, profile = await self._require_manage_topics(chat)
        if getattr(chat, "type", None) == "private":
            raise ForumTopicError("Reopening topics is not available in private chats through the Telegram Bot API.")
        topic_id = self._validate_topic_id(topic_id)
        if topic_id == GENERAL_TOPIC_ID and getattr(chat, "type", None) != "private":
            await self.bot.reopen_general_forum_topic(chat_id=chat.id)
        else:
            await self.bot.reopen_forum_topic(
                chat_id=chat.id, message_thread_id=topic_id
            )
        current = await self.store.get_topic(chat.id, topic_id)
        await self.store.upsert_topic_lifecycle(
            chat.id, topic_id, name=(current or {}).get("name"),
            is_active=True, is_closed=False
        )
        return True

    async def _require_delete_topic(self, chat):
        """Validate the Bot API permission actually required by deleteForumTopic.

        Topic deletion in a supergroup requires can_delete_messages, not
        can_manage_topics. Private bot topics have no chat-admin permission.
        """
        context, caps, profile = await self._context(chat)
        if getattr(chat, "type", None) == "private":
            return context, caps, profile

        try:
            me = await self.bot.get_me()
            permissions = await resolve_bot_permissions(chat, me.id)
        except Exception as exc:
            logger.exception("Forum delete permission lookup failed")
            raise ForumTopicError("Could not verify the bot's message-deletion permission.") from exc

        if not permissions.is_admin or not permissions.can_delete_messages:
            raise ForumTopicError("Ghostea needs the Delete Messages admin permission to delete a forum topic.")
        return context, caps, profile

    async def delete_topic(self, chat, topic_id):
        await self._require_delete_topic(chat)
        topic_id = self._validate_topic_id(topic_id)
        if topic_id == GENERAL_TOPIC_ID and getattr(chat, "type", None) != "private":
            raise ForumTopicError("The General topic cannot be deleted.")
        await self.bot.delete_forum_topic(
            chat_id=chat.id, message_thread_id=topic_id
        )
        current = await self.store.get_topic(chat.id, topic_id)
        await self.store.upsert_topic_lifecycle(
            chat.id, topic_id, name=(current or {}).get("name"),
            is_active=False, is_closed=True
        )
        return True
