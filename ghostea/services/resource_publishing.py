"""Phase 7 — Telegram publishing for resource/config and flag uploads."""
import html
import secrets
import asyncio
from datetime import datetime, timezone
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatType

from ghostea.services.upload_workflow import UploadMode, UploadState, UploadWorkflowError, MAX_DESCRIPTION_LENGTH
from ghostea.services.telegram_resilience import TelegramErrorPolicy
from ghostea.services.forum_topic_service import GENERAL_TOPIC_ID

MAX_RESOURCE_ID = 16


class ResourcePublishError(RuntimeError):
    """Expected publishing failure safe to show to the Telegram user."""


class ResourcePublishingService:
    def __init__(self, store, workflow, group_authorization, forum_topics, bot):
        self.store = store
        self.workflow = workflow
        self.group_authorization = group_authorization
        self.forum_topics = forum_topics
        self.bot = bot
        self.telegram_policy = TelegramErrorPolicy()
        self._publish_locks = {}
        self._publish_locks_guard = asyncio.Lock()

    @staticmethod
    def _id():
        return secrets.token_urlsafe(12).replace("-", "").replace("_", "")[:MAX_RESOURCE_ID]

    async def _revalidate(self, session):
        try:
            return await self.workflow._revalidate_target(session, session.user_id)
        except UploadWorkflowError as exc:
            raise ResourcePublishError(str(exc)) from exc

    @staticmethod
    def _thread_kwargs(chat, topic_id):
        if topic_id is None or int(topic_id) == GENERAL_TOPIC_ID:
            return {}
        if getattr(chat, "type", None) == ChatType.SUPERGROUP and getattr(chat, "is_forum", False):
            return {"message_thread_id": int(topic_id)}
        raise ResourcePublishError("The selected topic is no longer valid for this chat.")

    @staticmethod
    def _resource_text(p):
        return (
            f"<b>{html.escape(str(p.get('caption') or ''))}</b>\n\n"
            f"{html.escape(str(p.get('description') or ''))}"
        )

    @staticmethod
    def _flag_caption(p):
        # Keep the flag fields copy-friendly and safely escaped. The longer
        # description is published as a separate message to avoid Telegram's
        # media-caption limit truncating required metadata.
        return (
            f"<b>Main-Flag</b>\n<code>{html.escape(str(p.get('main_flag') or ''))}</code>\n\n"
            f"<b>Sub-Flags</b>\n<code>{html.escape(str(p.get('sub_flags') or ''))}</code>"
        )

    async def _save_resource(self, *, resource_id, session, source_kind, source_file_id=None, source_url=None, published_message_id=None, published_extra_message_id=None):
        p = session.payload
        now = datetime.now(timezone.utc).isoformat()
        return await self.store.create_resource({
            "resource_id": resource_id,
            "workflow_session_id": session.session_id,
            "chat_id": int(session.chat_id),
            "topic_id": int(session.topic_id) if session.topic_id is not None else None,
            "mode": session.mode,
            "source_kind": source_kind,
            "source_file_id": source_file_id,
            "source_url": source_url,
            "caption": p.get("caption"),
            "description": p.get("description") or "",
            "main_flag": p.get("main_flag"),
            "sub_flags": p.get("sub_flags"),
            "published_message_id": published_message_id,
            "published_extra_message_id": published_extra_message_id,
            "created_by": int(session.user_id),
            "created_at": now,
            "updated_at": now,
        })

    async def _publish_lock(self, session_id):
        async with self._publish_locks_guard:
            lock = self._publish_locks.get(str(session_id))
            if lock is None:
                lock = asyncio.Lock()
                self._publish_locks[str(session_id)] = lock
            # Keep the map bounded; never remove a lock that is currently held.
            if len(self._publish_locks) > 20000:
                for key, candidate in list(self._publish_locks.items())[:1000]:
                    if not candidate.locked():
                        self._publish_locks.pop(key, None)
            return lock

    async def publish(self, session_id, user_id):
        lock = await self._publish_lock(session_id)
        async with lock:
            return await self._publish_locked(session_id, user_id)

    async def _publish_locked(self, session_id, user_id):
        # Atomically claim READY -> PUBLISHING so duplicate callback presses
        # cannot publish the same session twice (including across workers).
        claimed = await self.store.claim_upload_for_publish(session_id, user_id)
        if not claimed:
            session = await self.workflow.get(session_id, user_id, allow_terminal=True)
            if session.state == "publishing":
                raise ResourcePublishError("This upload is already being published.")
            if session.state == UploadState.CANCELLED.value:
                raise ResourcePublishError("This upload has already been published or cancelled.")
            raise ResourcePublishError("This upload is not ready to publish. Please complete the workflow first.")
        session = self.workflow._as_session(claimed)
        existing = await self.store.get_resource_by_session(session.session_id)
        if existing:
            await self.store.update_upload_session(session.session_id, state=UploadState.CANCELLED.value)
            return str(existing["resource_id"])
        try:
            return await self._publish_claimed(session, user_id)
        except Exception:
            # Make transient Telegram errors retryable; a successful publish
            # is recorded before this method returns, so duplicate claims are
            # still blocked by the durable state transition.
            await self.store.update_upload_session(session.session_id, state=UploadState.READY.value)
            raise

    async def _publish_claimed(self, session, user_id):
        if session.user_id != int(user_id):
            raise ResourcePublishError("This upload session belongs to another user.")
        chat = await self._revalidate(session)
        p = session.payload
        resource_id = self._id()

        # Telegram does not allow sending a message into a closed forum topic.
        # If the bot has can_manage_topics, reopen it first, then publish.
        if session.topic_id is not None and int(session.topic_id) != GENERAL_TOPIC_ID:
            topic = await self.store.get_topic(chat.id, int(session.topic_id))
            if topic and topic.get("is_closed"):
                try:
                    await self.forum_topics.reopen_topic(chat, int(session.topic_id))
                except Exception as exc:
                    raise ResourcePublishError(
                        "❌ The selected topic is closed and the bot cannot reopen it. "
                        "Give the bot Manage Topics permission or reopen the topic manually."
                    ) from exc

        thread = self._thread_kwargs(chat, session.topic_id)

        if session.mode == UploadMode.RESOURCE.value:
            source = p.get("source") or {}
            kind = str(source.get("kind") or "")
            if kind == "url":
                markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Open / Download", url=str(source["url"]))]])
                sent = await self.telegram_policy.call_write_rate_limited(lambda: chat.send_message(self._resource_text(p), parse_mode="HTML", reply_markup=markup, **thread), scope_id=chat.id)
                await self._save_resource(resource_id=resource_id, session=session, source_kind="url", source_url=source["url"], published_message_id=sent.message_id)
            else:
                file_id = str(source.get("file_id") or "")
                if not file_id:
                    raise ResourcePublishError("The uploaded Telegram file is missing.")
                markup = InlineKeyboardMarkup([[InlineKeyboardButton("📥 Download", callback_data=f"resource:{resource_id}")]])
                sent = await self.telegram_policy.call_write_rate_limited(lambda: chat.send_message(self._resource_text(p), parse_mode="HTML", reply_markup=markup, **thread), scope_id=chat.id)
                await self._save_resource(resource_id=resource_id, session=session, source_kind=kind, source_file_id=file_id, published_message_id=sent.message_id)
        else:
            image = p.get("image") or {}
            image_id = str(image.get("file_id") or "")
            if not image_id:
                raise ResourcePublishError("The flag image is missing.")
            sent = await self.telegram_policy.call_write_rate_limited(lambda: chat.send_photo(image_id, caption=self._flag_caption(p), parse_mode="HTML", **thread), scope_id=chat.id)
            extra = await self.telegram_policy.call_write_rate_limited(lambda: chat.send_message(html.escape(str(p.get("description") or "")), parse_mode="HTML", **thread), scope_id=chat.id)
            await self._save_resource(resource_id=resource_id, session=session, source_kind="photo", source_file_id=image_id, published_message_id=sent.message_id, published_extra_message_id=extra.message_id)

        await self.store.update_upload_session(session.session_id, state=UploadState.CANCELLED.value)
        return resource_id

    async def deliver_download(self, resource_id, user_id):
        row = await self.store.get_resource(resource_id)
        if not row or not row.get("source_file_id"):
            raise ResourcePublishError("This download is no longer available.")
        file_id = str(row["source_file_id"])
        kind = str(row.get("source_kind") or "")
        caption = str(row.get("caption") or "")
        chat_id = int(user_id)
        kwargs = {"chat_id": chat_id, "caption": caption} if caption else {"chat_id": chat_id}
        if kind == "document":
            await self.telegram_policy.call_write_rate_limited(lambda: self.bot.send_document(document=file_id, **kwargs), scope_id=chat_id)
        elif kind == "photo":
            await self.telegram_policy.call_write_rate_limited(lambda: self.bot.send_photo(photo=file_id, **kwargs), scope_id=chat_id)
        elif kind == "video":
            await self.telegram_policy.call_write_rate_limited(lambda: self.bot.send_video(video=file_id, **kwargs), scope_id=chat_id)
        elif kind == "audio":
            await self.telegram_policy.call_write_rate_limited(lambda: self.bot.send_audio(audio=file_id, **kwargs), scope_id=chat_id)
        elif kind == "animation":
            await self.telegram_policy.call_write_rate_limited(lambda: self.bot.send_animation(animation=file_id, **kwargs), scope_id=chat_id)
        else:
            raise ResourcePublishError("This file type cannot be downloaded through Ghostea yet.")
