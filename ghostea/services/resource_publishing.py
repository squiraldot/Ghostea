"""Phase 7 — Telegram publishing for resource/config and flag uploads."""
import html
import secrets
import asyncio
import io
import re
from datetime import datetime, timezone
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.constants import ChatType

from ghostea.services.upload_workflow import UploadMode, UploadState, UploadWorkflowError, MAX_DESCRIPTION_LENGTH
from ghostea.services.telegram_resilience import TelegramErrorPolicy
from ghostea.services.forum_topic_service import GENERAL_TOPIC_ID

MAX_RESOURCE_ID = 16


class ResourcePublishError(RuntimeError):
    """Expected publishing failure safe to show to the Telegram user."""


class ResourcePublishingService:
    def __init__(self, store, workflow, group_authorization, forum_topics, bot, storage=None):
        self.store = store
        self.workflow = workflow
        self.group_authorization = group_authorization
        self.forum_topics = forum_topics
        self.bot = bot
        self.storage = storage
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

    async def _save_resource(self, *, resource_id, session, source_kind, source_file_id=None, source_url=None,
                             published_message_id=None, published_extra_message_id=None,
                             storage_key=None, storage_filename=None, storage_size=None, storage_content_type=None):
        p = session.payload
        now = datetime.now(timezone.utc).isoformat()
        row = {
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
        }
        if storage_key is not None:
            row.update({
                "storage_key": storage_key,
                "storage_filename": storage_filename,
                "storage_size": storage_size,
                "storage_content_type": storage_content_type,
            })
        return await self.store.create_resource(row)

    @staticmethod
    def _safe_filename(name, fallback):
        name = str(name or "").strip().replace("\\", "_").replace("/", "_")
        name = re.sub(r"[^A-Za-z0-9._ -]", "_", name).strip(" .")
        return (name[:180] or fallback)

    async def _archive_file(self, *, resource_id, file_id, filename, content_type, kind):
        if self.storage is None:
            return None
        fallback_ext = {"photo": ".jpg", "video": ".mp4", "audio": ".mp3", "animation": ".gif"}.get(kind, ".bin")
        safe_name = self._safe_filename(filename, f"{resource_id}{fallback_ext}")
        key = f"resources/{resource_id}/{safe_name}"

        async def fetch():
            tg_file = await self.bot.get_file(file_id)
            return await tg_file.download_as_bytearray()

        data = await self.telegram_policy.call_read(fetch)
        size = len(data)
        try:
            stored_key = await asyncio.to_thread(self.storage.put, key, bytes(data), content_type)
        except (ValueError, RuntimeError, OSError) as exc:
            raise ResourcePublishError("❌ File could not be saved to the configured storage.") from exc
        return {"key": str(stored_key), "filename": safe_name, "size": size, "content_type": content_type}

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
                archived = await self._archive_file(
                    resource_id=resource_id,
                    file_id=file_id,
                    filename=source.get("file_name"),
                    content_type=source.get("mime_type"),
                    kind=kind,
                )
                markup = InlineKeyboardMarkup([[InlineKeyboardButton("📥 Download", callback_data=f"resource:{resource_id}")]])
                sent = await self.telegram_policy.call_write_rate_limited(lambda: chat.send_message(self._resource_text(p), parse_mode="HTML", reply_markup=markup, **thread), scope_id=chat.id)
                await self._save_resource(
                    resource_id=resource_id, session=session, source_kind=kind,
                    source_file_id=file_id, published_message_id=sent.message_id,
                    storage_key=archived["key"] if archived else None,
                    storage_filename=archived["filename"] if archived else None,
                    storage_size=archived["size"] if archived else None,
                    storage_content_type=archived["content_type"] if archived else None,
                )
        else:
            image = p.get("image") or {}
            image_id = str(image.get("file_id") or "")
            if not image_id:
                raise ResourcePublishError("The flag image is missing.")
            archived = await self._archive_file(
                resource_id=resource_id,
                file_id=image_id,
                filename=None,
                content_type="image/jpeg",
                kind="photo",
            )
            sent = await self.telegram_policy.call_write_rate_limited(lambda: chat.send_photo(image_id, caption=self._flag_caption(p), parse_mode="HTML", **thread), scope_id=chat.id)
            extra = await self.telegram_policy.call_write_rate_limited(lambda: chat.send_message(html.escape(str(p.get("description") or "")), parse_mode="HTML", **thread), scope_id=chat.id)
            await self._save_resource(
                resource_id=resource_id, session=session, source_kind="photo", source_file_id=image_id,
                published_message_id=sent.message_id, published_extra_message_id=extra.message_id,
                storage_key=archived["key"] if archived else None,
                storage_filename=archived["filename"] if archived else None,
                storage_size=archived["size"] if archived else None,
                storage_content_type=archived["content_type"] if archived else None,
            )

        await self.store.update_upload_session(session.session_id, state=UploadState.CANCELLED.value)
        return resource_id

    async def deliver_download(self, resource_id, user_id):
        row = await self.store.get_resource(resource_id)
        if not row:
            raise ResourcePublishError("This download is no longer available.")

        kind = str(row.get("source_kind") or "")
        caption = str(row.get("caption") or "")
        chat_id = int(user_id)

        # Self-hosted resources are served from the VPS copy. Managed mode keeps
        # the existing Telegram file_id path until the remote storage adapter is
        # introduced.
        storage_key = row.get("storage_key")
        if self.storage is not None and storage_key:
            try:
                data = await asyncio.to_thread(self.storage.get, str(storage_key))
            except FileNotFoundError as exc:
                raise ResourcePublishError("This local file is missing from VPS storage.") from exc
            filename = str(row.get("storage_filename") or f"{resource_id}.bin")
            document = InputFile(io.BytesIO(data), filename=filename)
            if kind == "document":
                await self.telegram_policy.call_write_rate_limited(
                    lambda: self.bot.send_document(chat_id=chat_id, document=document, caption=caption or None),
                    scope_id=chat_id,
                )
            elif kind == "photo":
                await self.telegram_policy.call_write_rate_limited(
                    lambda: self.bot.send_photo(chat_id=chat_id, photo=document, caption=caption or None),
                    scope_id=chat_id,
                )
            elif kind == "video":
                await self.telegram_policy.call_write_rate_limited(
                    lambda: self.bot.send_video(chat_id=chat_id, video=document, caption=caption or None),
                    scope_id=chat_id,
                )
            elif kind == "audio":
                await self.telegram_policy.call_write_rate_limited(
                    lambda: self.bot.send_audio(chat_id=chat_id, audio=document, caption=caption or None),
                    scope_id=chat_id,
                )
            elif kind == "animation":
                await self.telegram_policy.call_write_rate_limited(
                    lambda: self.bot.send_animation(chat_id=chat_id, animation=document, caption=caption or None),
                    scope_id=chat_id,
                )
            else:
                raise ResourcePublishError("This file type cannot be downloaded through Ghostea yet.")
            return

        file_id = str(row.get("source_file_id") or "")
        if not file_id:
            raise ResourcePublishError("This download is no longer available.")
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
