"""Phase 7 — Telegram publishing for resource/config and flag uploads."""
import html
import secrets
from datetime import datetime, timezone
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatType

from ghostea.services.upload_workflow import UploadMode, UploadState, UploadWorkflowError, MAX_DESCRIPTION_LENGTH
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

    async def publish(self, session_id, user_id):
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

        # Telegram rejects sends to closed topics. There is no separate
        # "post while closed" permission; the supported admin capability is
        # can_manage_topics, which lets the bot reopen the topic. For upload
        # publishing, honor that capability by reopening a closed (but visible
        # and active) topic immediately before sending. Hidden General and
        # deleted/inactive topics are rejected by _revalidate().
        if session.topic_id is not None:
            rows = await self.forum_topics.list_topics(chat, include_inactive=True, limit=200)
            selected = next((r for r in rows if int(r.get("topic_id", 0)) == int(session.topic_id)), None)
            if selected is None or not selected.get("is_active", True) or selected.get("is_hidden", False):
                raise ResourcePublishError("❌ The selected topic is hidden, deleted, or no longer available.")
            if selected.get("is_closed", False):
                try:
                    await self.forum_topics.reopen_topic(chat, int(session.topic_id))
                except Exception as exc:
                    raise ResourcePublishError(
                        "❌ The selected topic is closed and Ghostea cannot reopen it with the bot's current Manage Topics permission."
                    ) from exc

        thread = self._thread_kwargs(chat, session.topic_id)

        if session.mode == UploadMode.RESOURCE.value:
            source = p.get("source") or {}
            kind = str(source.get("kind") or "")
            if kind == "url":
                markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Open / Download", url=str(source["url"]))]])
                sent = await chat.send_message(self._resource_text(p), parse_mode="HTML", reply_markup=markup, **thread)
                await self._save_resource(resource_id=resource_id, session=session, source_kind="url", source_url=source["url"], published_message_id=sent.message_id)
            else:
                file_id = str(source.get("file_id") or "")
                if not file_id:
                    raise ResourcePublishError("The uploaded Telegram file is missing.")
                markup = InlineKeyboardMarkup([[InlineKeyboardButton("📥 Download", callback_data=f"resource:{resource_id}")]])
                sent = await chat.send_message(self._resource_text(p), parse_mode="HTML", reply_markup=markup, **thread)
                await self._save_resource(resource_id=resource_id, session=session, source_kind=kind, source_file_id=file_id, published_message_id=sent.message_id)
        else:
            image = p.get("image") or {}
            image_id = str(image.get("file_id") or "")
            if not image_id:
                raise ResourcePublishError("The flag image is missing.")
            sent = await chat.send_photo(image_id, caption=self._flag_caption(p), parse_mode="HTML", **thread)
            extra = await chat.send_message(html.escape(str(p.get("description") or "")), parse_mode="HTML", **thread)
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
            await self.bot.send_document(document=file_id, **kwargs)
        elif kind == "photo":
            await self.bot.send_photo(photo=file_id, **kwargs)
        elif kind == "video":
            await self.bot.send_video(video=file_id, **kwargs)
        elif kind == "audio":
            await self.bot.send_audio(audio=file_id, **kwargs)
        elif kind == "animation":
            await self.bot.send_animation(animation=file_id, **kwargs)
        else:
            raise ResourcePublishError("This file type cannot be downloaded through Ghostea yet.")
