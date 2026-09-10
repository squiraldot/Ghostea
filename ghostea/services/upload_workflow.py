"""Phase 6 — DM upload workflow state machine.

This module owns the multi-step /uploadconfig and /uploadflag flows.  Handlers
are intentionally thin: authorization, state transitions, expiry, ownership,
and payload validation live here so future upload/publish surfaces can reuse
one workflow engine.
"""
import asyncio
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from urllib.parse import urlparse

from telegram.constants import ChatMemberStatus, ChatType

from ghostea.services.forum_topic_service import GENERAL_TOPIC_ID

SESSION_TTL_SECONDS = 15 * 60
MAX_CAPTION_LENGTH = 1024
MAX_DESCRIPTION_LENGTH = 4096
MAX_URL_LENGTH = 2048
MAX_TOPICS = 200
MAX_GROUPS = 500


class UploadMode(str, Enum):
    RESOURCE = "resource"
    FLAG = "flag"


class UploadState(str, Enum):
    SELECT_GROUP = "select_group"
    SELECT_TOPIC = "select_topic"
    SELECT_SOURCE = "select_source"
    WAIT_FILE = "wait_file"
    WAIT_URL = "wait_url"
    WAIT_CAPTION = "wait_caption"
    WAIT_DESCRIPTION = "wait_description"
    WAIT_FLAG_IMAGE = "wait_flag_image"
    WAIT_MAIN_FLAG = "wait_main_flag"
    WAIT_SUB_FLAGS = "wait_sub_flags"
    WAIT_FLAG_DESCRIPTION = "wait_flag_description"
    CONFIRM = "confirm"
    READY = "ready"
    PUBLISHING = "publishing"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


@dataclass(frozen=True)
class UploadSession:
    session_id: str
    user_id: int
    chat_id: int
    topic_id: int | None
    mode: str
    state: str
    payload: dict
    created_at: datetime
    expires_at: datetime


class UploadWorkflowError(RuntimeError):
    """Expected workflow error safe to show to the Telegram user."""


class UploadWorkflowEngine:
    def __init__(self, store, group_authorization, forum_topics, bot, *, ttl_seconds=SESSION_TTL_SECONDS):
        self.store = store
        self.group_authorization = group_authorization
        self.forum_topics = forum_topics
        self.bot = bot
        self.ttl_seconds = int(ttl_seconds)
        self._locks = {}

    async def _lock(self, session_id):
        lock = self._locks.get(session_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[session_id] = lock
        return lock

    @staticmethod
    def _now():
        return datetime.now(timezone.utc)

    @staticmethod
    def _new_id():
        # 16 url-safe chars keeps callback_data comfortably below Telegram's
        # 64-byte limit even after adding action prefixes.
        return secrets.token_urlsafe(12).replace("-", "").replace("_", "")[:16]

    @staticmethod
    def _as_session(row):
        if not row:
            return None
        def dt(value):
            if isinstance(value, datetime):
                return value
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return UploadSession(
            session_id=str(row["session_id"]), user_id=int(row["user_id"]),
            chat_id=int(row["chat_id"]),
            topic_id=int(row["topic_id"]) if row.get("topic_id") is not None else None,
            mode=str(row["mode"]), state=str(row["state"]),
            payload=dict(row.get("payload") or {}),
            created_at=dt(row["created_at"]), expires_at=dt(row["expires_at"]),
        )

    async def _get_owned(self, session_id, user_id, *, allow_terminal=False):
        session = self._as_session(await self.store.get_upload_session(session_id))
        if not session:
            raise UploadWorkflowError("This upload session is no longer available. Please start again.")
        if session.user_id != int(user_id):
            raise UploadWorkflowError("This upload session belongs to another user.")
        if session.expires_at <= self._now() and session.state not in (UploadState.CANCELLED.value, UploadState.EXPIRED.value):
            await self.store.update_upload_session(session.session_id, state=UploadState.EXPIRED.value)
            raise UploadWorkflowError("This upload session expired. Please start again.")
        if not allow_terminal and session.state in (UploadState.CANCELLED.value, UploadState.EXPIRED.value, UploadState.READY.value):
            raise UploadWorkflowError("This upload session is already closed. Please start again.")
        return session

    async def _save(self, session, *, state=None, payload=None, chat_id=None, topic_id="__keep__"):
        expires = self._now() + timedelta(seconds=self.ttl_seconds)
        return await self.store.update_upload_session(
            session.session_id,
            state=state or session.state,
            payload=session.payload if payload is None else payload,
            chat_id=session.chat_id if chat_id is None else int(chat_id),
            topic_id=session.topic_id if topic_id == "__keep__" else topic_id,
            expires_at=expires.isoformat(),
        )

    async def start(self, user_id, mode):
        mode = UploadMode(mode).value
        groups = await self.group_authorization.list_authorized_groups(int(user_id), limit=MAX_GROUPS)
        if not groups:
            raise UploadWorkflowError("❌ I couldn't find any linked group where you are currently a Telegram admin.")
        now = self._now()
        # Keep one active workflow per Telegram user. This prevents two DM
        # conversations from racing for the same next message.
        previous = await self.store.latest_active_upload_session(int(user_id))
        if previous:
            await self.store.update_upload_session(
                previous["session_id"], state=UploadState.CANCELLED.value,
                expires_at=now.isoformat()
            )
        session_id = self._new_id()
        payload = {"groups": [
            {"chat_id": int(g.chat_id), "title": g.title or str(g.chat_id),
             "chat_type": g.chat_type, "is_forum": bool(g.is_forum)} for g in groups
        ]}
        await self.store.create_upload_session(
            session_id=session_id, user_id=int(user_id), chat_id=int(groups[0].chat_id),
            topic_id=None, mode=mode, state=UploadState.SELECT_GROUP.value,
            payload=payload, created_at=now.isoformat(),
            expires_at=(now + timedelta(seconds=self.ttl_seconds)).isoformat(),
        )
        return self._as_session(await self.store.get_upload_session(session_id))

    async def select_group(self, session_id, user_id, index):
        async with await self._lock(session_id):
            s = await self._get_owned(session_id, user_id)
            if s.state != UploadState.SELECT_GROUP.value:
                raise UploadWorkflowError("The group selection step is no longer active.")
            groups = s.payload.get("groups") or []
            try:
                item = groups[int(index)]
            except (ValueError, TypeError, IndexError):
                raise UploadWorkflowError("Invalid group selection.")
            chat_id = int(item["chat_id"])
            authorized = await self.group_authorization.list_authorized_groups(int(user_id), limit=MAX_GROUPS)
            if not any(int(g.chat_id) == chat_id for g in authorized):
                raise UploadWorkflowError("❌ Your admin access to this group is no longer valid.")
            chat = await self.bot.get_chat(chat_id)
            is_forum = bool(getattr(chat, "type", None) == ChatType.SUPERGROUP and getattr(chat, "is_forum", False))
            payload = dict(s.payload)
            payload.update({"selected_group": {"chat_id": chat_id, "title": getattr(chat, "title", None) or item.get("title") or str(chat_id), "is_forum": is_forum}})
            if is_forum:
                topics = await self.forum_topics.list_selectable_topics(chat, limit=MAX_TOPICS)
                payload["topics"] = [{"topic_id": int(t["topic_id"]), "name": t.get("name") or f"Topic {t['topic_id']}"} for t in topics]
                await self._save(s, state=UploadState.SELECT_TOPIC.value, payload=payload, chat_id=chat_id, topic_id=None)
            else:
                payload.pop("topics", None)
                next_state = UploadState.SELECT_SOURCE.value if s.mode == UploadMode.RESOURCE.value else UploadState.WAIT_FLAG_IMAGE.value
                await self._save(s, state=next_state, payload=payload, chat_id=chat_id, topic_id=None)
            return self._as_session(await self.store.get_upload_session(session_id))

    async def select_topic(self, session_id, user_id, index):
        async with await self._lock(session_id):
            s = await self._get_owned(session_id, user_id)
            if s.state != UploadState.SELECT_TOPIC.value:
                raise UploadWorkflowError("The topic selection step is no longer active.")
            topics = s.payload.get("topics") or []
            try:
                item = topics[int(index)]
            except (ValueError, TypeError, IndexError):
                raise UploadWorkflowError("Invalid topic selection.")
            chat_id = int(s.chat_id)
            chat = await self.bot.get_chat(chat_id)
            if getattr(chat, "type", None) != ChatType.SUPERGROUP or not getattr(chat, "is_forum", False):
                raise UploadWorkflowError("❌ This group is no longer a forum.")
            fresh = await self.forum_topics.list_selectable_topics(chat, limit=MAX_TOPICS)
            topic_id = int(item["topic_id"])
            if not any(int(t["topic_id"]) == topic_id for t in fresh):
                raise UploadWorkflowError("❌ That topic is no longer available. Please start again.")
            payload = dict(s.payload)
            payload["selected_topic"] = {"topic_id": topic_id, "name": item.get("name") or f"Topic {topic_id}"}
            next_state = UploadState.SELECT_SOURCE.value if s.mode == UploadMode.RESOURCE.value else UploadState.WAIT_FLAG_IMAGE.value
            await self._save(s, state=next_state, payload=payload, topic_id=topic_id)
            return self._as_session(await self.store.get_upload_session(session_id))

    async def choose_source(self, session_id, user_id, source):
        async with await self._lock(session_id):
            s = await self._get_owned(session_id, user_id)
            if s.state != UploadState.SELECT_SOURCE.value or s.mode != UploadMode.RESOURCE.value:
                raise UploadWorkflowError("The source-selection step is not active.")
            if source not in ("file", "url"):
                raise UploadWorkflowError("Choose File or URL.")
            state = UploadState.WAIT_FILE.value if source == "file" else UploadState.WAIT_URL.value
            payload = dict(s.payload); payload["source_type"] = source
            await self._save(s, state=state, payload=payload)
            return self._as_session(await self.store.get_upload_session(session_id))

    @staticmethod
    def _extract_file(message):
        candidates = [
            ("document", getattr(message, "document", None)),
            ("video", getattr(message, "video", None)),
            ("audio", getattr(message, "audio", None)),
            ("animation", getattr(message, "animation", None)),
            ("photo", (getattr(message, "photo", None) or [None])[-1]),
        ]
        for kind, obj in candidates:
            if obj and getattr(obj, "file_id", None):
                return {"kind": kind, "file_id": str(obj.file_id), "file_unique_id": getattr(obj, "file_unique_id", None),
                        "file_name": getattr(obj, "file_name", None), "mime_type": getattr(obj, "mime_type", None)}
        return None

    async def receive_resource(self, session_id, user_id, message):
        async with await self._lock(session_id):
            s = await self._get_owned(session_id, user_id)
            if s.state == UploadState.WAIT_FILE.value:
                file_data = self._extract_file(message)
                if not file_data:
                    raise UploadWorkflowError("❌ Please send a Telegram file (document, photo, video, audio, or animation).")
                payload = dict(s.payload); payload["source"] = file_data
                await self._save(s, state=UploadState.WAIT_CAPTION.value, payload=payload)
            elif s.state == UploadState.WAIT_URL.value:
                text = str(getattr(message, "text", "") or "").strip()
                parsed = urlparse(text)
                if len(text) > MAX_URL_LENGTH or parsed.scheme not in ("http", "https") or not parsed.netloc:
                    raise UploadWorkflowError("❌ Send a valid http/https URL (max 2048 characters).")
                payload = dict(s.payload); payload["source"] = {"kind": "url", "url": text}
                await self._save(s, state=UploadState.WAIT_CAPTION.value, payload=payload)
            else:
                raise UploadWorkflowError("The file/URL step is not active.")
            return self._as_session(await self.store.get_upload_session(session_id))

    async def receive_caption(self, session_id, user_id, text):
        async with await self._lock(session_id):
            s = await self._get_owned(session_id, user_id)
            if s.state != UploadState.WAIT_CAPTION.value:
                raise UploadWorkflowError("The caption step is not active.")
            text = str(text or "").strip()
            if not text or len(text) > MAX_CAPTION_LENGTH:
                raise UploadWorkflowError("❌ Caption is mandatory and must be 1024 characters or fewer.")
            payload = dict(s.payload); payload["caption"] = text
            await self._save(s, state=UploadState.WAIT_DESCRIPTION.value, payload=payload)
            return self._as_session(await self.store.get_upload_session(session_id))

    async def receive_description(self, session_id, user_id, text):
        async with await self._lock(session_id):
            s = await self._get_owned(session_id, user_id)
            if s.state != UploadState.WAIT_DESCRIPTION.value:
                raise UploadWorkflowError("The description step is not active.")
            text = str(text or "").strip()
            if not text or len(text) > MAX_DESCRIPTION_LENGTH:
                raise UploadWorkflowError("❌ Description is mandatory and must be 4096 characters or fewer.")
            payload = dict(s.payload); payload["description"] = text
            await self._save(s, state=UploadState.CONFIRM.value, payload=payload)
            return self._as_session(await self.store.get_upload_session(session_id))

    async def receive_flag_image(self, session_id, user_id, message):
        async with await self._lock(session_id):
            s = await self._get_owned(session_id, user_id)
            if s.state != UploadState.WAIT_FLAG_IMAGE.value:
                raise UploadWorkflowError("The flag image step is not active.")
            photo = (getattr(message, "photo", None) or [])
            image = photo[-1] if photo else getattr(message, "document", None)
            if not image or not getattr(image, "file_id", None):
                raise UploadWorkflowError("❌ Please send an image.")
            payload = dict(s.payload); payload["image"] = {"file_id": str(image.file_id), "file_unique_id": getattr(image, "file_unique_id", None)}
            await self._save(s, state=UploadState.WAIT_MAIN_FLAG.value, payload=payload)
            return self._as_session(await self.store.get_upload_session(session_id))

    async def receive_flag_text(self, session_id, user_id, text, field):
        async with await self._lock(session_id):
            s = await self._get_owned(session_id, user_id)
            expected = {
                "main": UploadState.WAIT_MAIN_FLAG.value,
                "sub": UploadState.WAIT_SUB_FLAGS.value,
                "description": UploadState.WAIT_FLAG_DESCRIPTION.value,
            }.get(field)
            if s.state != expected:
                raise UploadWorkflowError("That flag step is not active.")
            text = str(text or "").strip()
            if not text or len(text) > MAX_DESCRIPTION_LENGTH:
                raise UploadWorkflowError("❌ This field is mandatory.")
            payload = dict(s.payload); payload[{"main":"main_flag","sub":"sub_flags","description":"description"}[field]] = text
            next_state = {"main": UploadState.WAIT_SUB_FLAGS.value, "sub": UploadState.WAIT_FLAG_DESCRIPTION.value, "description": UploadState.CONFIRM.value}[field]
            await self._save(s, state=next_state, payload=payload)
            return self._as_session(await self.store.get_upload_session(session_id))

    async def confirm(self, session_id, user_id):
        async with await self._lock(session_id):
            s = await self._get_owned(session_id, user_id)
            if s.state != UploadState.CONFIRM.value:
                raise UploadWorkflowError("There is nothing ready to upload yet.")
            self._validate_payload(s)
            # Authorization is revalidated at the last step. Phase 7 will
            # perform the same check immediately before Telegram publish.
            await self._revalidate_target(s, user_id)
            await self._save(s, state=UploadState.READY.value)
            return self._as_session(await self.store.get_upload_session(session_id))

    def _validate_payload(self, s):
        p = s.payload
        if s.mode == UploadMode.RESOURCE.value:
            source = p.get("source") or {}
            if p.get("source_type") not in ("file", "url"):
                raise UploadWorkflowError("Source is missing.")
            if p["source_type"] == "file" and (source.get("kind") == "url" or not source.get("file_id")):
                raise UploadWorkflowError("Exactly one file source is required.")
            if p["source_type"] == "url" and (source.get("kind") != "url" or not source.get("url")):
                raise UploadWorkflowError("Exactly one URL source is required.")
            if not str(p.get("caption") or "").strip() or not str(p.get("description") or "").strip():
                raise UploadWorkflowError("Caption and description are mandatory.")
        else:
            for key in ("image", "main_flag", "sub_flags", "description"):
                if not str(p.get(key) or "").strip() and key != "image":
                    raise UploadWorkflowError("All flag fields are mandatory.")
            if not (p.get("image") or {}).get("file_id"):
                raise UploadWorkflowError("Flag image is mandatory.")

    async def _revalidate_target(self, s, user_id):
        groups = await self.group_authorization.list_authorized_groups(int(user_id), limit=MAX_GROUPS)
        target = next((g for g in groups if int(g.chat_id) == int(s.chat_id)), None)
        if target is None:
            raise UploadWorkflowError("❌ Your admin access to the selected group is no longer valid.")
        chat = await self.bot.get_chat(int(s.chat_id))
        if s.topic_id is not None:
            if getattr(chat, "type", None) != ChatType.SUPERGROUP or not getattr(chat, "is_forum", False):
                raise UploadWorkflowError("❌ The selected forum is no longer available.")
            fresh = await self.forum_topics.list_selectable_topics(chat, limit=MAX_TOPICS)
            if not any(int(t["topic_id"]) == int(s.topic_id) for t in fresh):
                raise UploadWorkflowError("❌ The selected topic is closed, hidden, deleted, or no longer available.")
        return chat

    async def cancel(self, session_id, user_id):
        async with await self._lock(session_id):
            s = await self._get_owned(session_id, user_id, allow_terminal=True)
            if s.state in (UploadState.CANCELLED.value, UploadState.EXPIRED.value):
                return s
            await self.store.update_upload_session(session_id, state=UploadState.CANCELLED.value, expires_at=self._now().isoformat())
            return self._as_session(await self.store.get_upload_session(session_id))

    async def get(self, session_id, user_id, *, allow_terminal=False):
        return await self._get_owned(session_id, user_id, allow_terminal=allow_terminal)
