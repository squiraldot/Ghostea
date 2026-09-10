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
ALLOWED_TOPIC_ICON_COLORS = frozenset({
    7322096, 16766590, 13338331, 9367192, 16749490, 16478047,
})


class ForumTopicError(RuntimeError):
    """Expected, user-facing forum operation failure."""


class ForumTopicService:
    def __init__(self, store, bot, permission_service=None):
        self.store = store
        self.bot = bot
        self.permission_service = permission_service

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
            if self.permission_service is not None:
                permissions = await self.permission_service.require_bot(chat, "manage_topics")
            else:
                me = await self.bot.get_me()
                permissions = await resolve_bot_permissions(chat, me.id, raise_on_error=True)
        except PermissionError as exc:
            raise ForumTopicError("Ghostea needs the Manage Topics admin permission in this forum.") from exc
        except Exception as exc:
            logger.exception("Forum permission lookup failed")
            raise ForumTopicError("Could not verify the bot's topic-management permission.") from exc
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
    def _topic_lifecycle_failure(error):
        """Return True only for errors that strongly indicate the topic is gone.

        Bot API does not expose a dedicated forum-topic-deleted update. For
        operations against a known topic, Telegram can instead reject the
        topic id. Only definitive topic-id/not-found errors retire local state;
        permission, transient, and generic bad-request errors never do.
        """
        text = str(error or "").upper()
        markers = (
            "TOPIC_ID_INVALID",
            "MESSAGE_THREAD_NOT_FOUND",
            "TOPIC_NOT_FOUND",
            "FORUM_TOPIC_NOT_FOUND",
            "MESSAGE_THREAD_ID_INVALID",
        )
        return any(marker in text for marker in markers)

    async def _mark_topic_stale(self, chat_id, topic_id, reason=None):
        current = await self.store.get_topic(chat_id, topic_id)
        await self.store.upsert_topic_lifecycle(
            chat_id,
            topic_id,
            name=(current or {}).get("name"),
            is_active=False,
            is_closed=True,
            is_hidden=False,
        )
        logger.info(
            "Retired stale forum topic %s/%s%s",
            int(chat_id),
            int(topic_id),
            f" reason={reason}" if reason else "",
        )

    @staticmethod
    def topic_id_from_update(update, private_topics_enabled=False):
        from ghostea.services.chat_context import build_chat_context
        ctx = build_chat_context(update.effective_chat, update.effective_message, private_topics_enabled=private_topics_enabled)
        return ctx.topic_id if ctx else None

    async def list_topics(self, chat, include_inactive=False, limit=200):
        context, caps, profile = await self._context(chat)
        rows = await self.store.list_topics(
            chat.id, include_inactive=include_inactive, limit=limit
        )

        # General is always present in a Telegram forum, but it does not emit
        # a message_thread_id on ordinary messages. Seed its local row so a
        # fresh forum can still expose a usable topic selector before Ghostea
        # has observed a custom-topic service message.
        if context.is_forum and int(limit) > 0:
            general = next((r for r in rows if int(r.get("topic_id", 0)) == GENERAL_TOPIC_ID), None)
            if general is None:
                existing = await self.store.get_topic(chat.id, GENERAL_TOPIC_ID)
                if existing:
                    general = existing
                else:
                    general = await self.store.upsert_topic_lifecycle(
                        chat.id, GENERAL_TOPIC_ID, name="General",
                        is_active=True, is_closed=False, is_hidden=False
                    )
                rows = [general] + rows
            else:
                # Keep General first regardless of registry update order.
                rows = [general] + [r for r in rows if r is not general]
        return rows[:max(1, min(int(limit), 500))]

    async def list_selectable_topics(self, chat, limit=200, include_closed=False):
        """Return topics safe for a future publish/upload selector.

        A topic must still be active, open, and visible. Telegram does not
        expose a Bot API method to enumerate forum topics, so this is backed by
        Ghostea's observed lifecycle registry and always revalidated at publish
        time by the caller.
        """
        rows = await self.list_topics(chat, include_inactive=False, limit=limit)
        # Closed topics are excluded from the normal topic selector. Upload
        # publishing may opt in with include_closed=True because the publish
        # layer can reopen a closed topic when the bot has can_manage_topics.
        selectable = [
            row for row in rows
            if row.get("is_active", True)
            and not row.get("is_hidden", False)
            and (include_closed or not row.get("is_closed", False))
        ]
        selectable.sort(key=lambda row: (0 if int(row.get("topic_id", 0)) == GENERAL_TOPIC_ID else 1, str(row.get("name") or "").lower()))
        return selectable[:max(1, min(int(limit), 500))]

    async def create_topic(self, chat, title, icon_color=None, icon_custom_emoji_id=None):
        await self._require_manage_topics(chat)
        title = self._validate_title(title)
        kwargs = {"chat_id": chat.id, "name": title}
        if icon_color is not None:
            try:
                icon_color = int(icon_color)
            except (TypeError, ValueError):
                raise ForumTopicError("Invalid topic icon color.")
            if icon_color not in ALLOWED_TOPIC_ICON_COLORS:
                raise ForumTopicError("Unsupported topic icon color.")
            kwargs["icon_color"] = icon_color
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
        try:
            if topic_id == GENERAL_TOPIC_ID and getattr(chat, "type", None) != "private":
                await self.bot.edit_general_forum_topic(chat_id=chat.id, name=title)
            else:
                await self.bot.edit_forum_topic(
                    chat_id=chat.id, message_thread_id=topic_id, name=title
                )
        except Exception as error:
            if self._topic_lifecycle_failure(error) and topic_id != GENERAL_TOPIC_ID:
                await self._mark_topic_stale(chat.id, topic_id, str(error))
            raise
        await self.store.upsert_topic_lifecycle(
            chat.id, topic_id, name=title, is_active=True, is_closed=False
        )
        return True

    async def close_topic(self, chat, topic_id):
        context, caps, profile = await self._require_manage_topics(chat)
        if getattr(chat, "type", None) == "private":
            raise ForumTopicError("Closing topics is not available in private chats through the Telegram Bot API.")
        topic_id = self._validate_topic_id(topic_id)
        try:
            if topic_id == GENERAL_TOPIC_ID and getattr(chat, "type", None) != "private":
                await self.bot.close_general_forum_topic(chat_id=chat.id)
            else:
                await self.bot.close_forum_topic(
                    chat_id=chat.id, message_thread_id=topic_id
                )
        except Exception as error:
            if self._topic_lifecycle_failure(error) and topic_id != GENERAL_TOPIC_ID:
                await self._mark_topic_stale(chat.id, topic_id, str(error))
            raise
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
        try:
            if topic_id == GENERAL_TOPIC_ID and getattr(chat, "type", None) != "private":
                await self.bot.reopen_general_forum_topic(chat_id=chat.id)
            else:
                await self.bot.reopen_forum_topic(
                    chat_id=chat.id, message_thread_id=topic_id
                )
        except Exception as error:
            if self._topic_lifecycle_failure(error) and topic_id != GENERAL_TOPIC_ID:
                await self._mark_topic_stale(chat.id, topic_id, str(error))
            raise
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
            if self.permission_service is not None:
                permissions = await self.permission_service.require_bot(chat, "delete_message")
            else:
                me = await self.bot.get_me()
                permissions = await resolve_bot_permissions(chat, me.id, raise_on_error=True)
        except PermissionError as exc:
            raise ForumTopicError("Ghostea needs the Delete Messages admin permission to delete a forum topic.") from exc
        except Exception as exc:
            logger.exception("Forum delete permission lookup failed")
            raise ForumTopicError("Could not verify the bot's message-deletion permission.") from exc
        return context, caps, profile

    async def delete_topic(self, chat, topic_id):
        await self._require_delete_topic(chat)
        topic_id = self._validate_topic_id(topic_id)
        if topic_id == GENERAL_TOPIC_ID and getattr(chat, "type", None) != "private":
            raise ForumTopicError("The General topic cannot be deleted.")
        try:
            await self.bot.delete_forum_topic(
                chat_id=chat.id, message_thread_id=topic_id
            )
        except Exception as error:
            if self._topic_lifecycle_failure(error):
                await self._mark_topic_stale(chat.id, topic_id, str(error))
            raise
        current = await self.store.get_topic(chat.id, topic_id)
        await self.store.upsert_topic_lifecycle(
            chat.id, topic_id, name=(current or {}).get("name"),
            is_active=False, is_closed=True
        )
        return True
