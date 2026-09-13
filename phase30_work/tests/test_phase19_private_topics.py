import unittest
from unittest.mock import AsyncMock
from pathlib import Path

from ghostea.services.chat_context import build_chat_context
from ghostea.services.chat_capabilities import (
    resolve_chat_capabilities,
    resolve_private_chat_topic_compatibility,
)
from ghostea.services.forum_topic_service import ForumTopicService, ForumTopicError


class FakeChat:
    def __init__(self, chat_id=777, chat_type="private"):
        self.id = chat_id
        self.type = chat_type
        self.title = ""
        self.first_name = "User"
        self.last_name = "Test"
        self.username = None
        self.is_forum = False


class FakeMessage:
    def __init__(self, thread=None):
        self.message_thread_id = thread


class FakeTopic:
    def __init__(self, name="Work", topic_id=42):
        self.name = name
        self.message_thread_id = topic_id


class FakeStore:
    def __init__(self):
        self.rows = {}
    async def list_topics(self, *args, **kwargs):
        return list(self.rows.values())
    async def get_topic(self, chat_id, topic_id):
        return self.rows.get((int(chat_id), int(topic_id)))
    async def upsert_topic_lifecycle(self, chat_id, topic_id, **kwargs):
        row = {"chat_id": int(chat_id), "topic_id": int(topic_id), **kwargs}
        self.rows[(int(chat_id), int(topic_id))] = row
        return row


class FakeBot:
    def __init__(self, enabled=True):
        self.create_forum_topic = AsyncMock(return_value=FakeTopic())
        self.edit_forum_topic = AsyncMock()
        self.delete_forum_topic = AsyncMock()
        self.get_me = AsyncMock(return_value=type("Me", (), {
            "id": 99, "has_topics_enabled": enabled
        })())


class Phase19PrivateTopicTests(unittest.IsolatedAsyncioTestCase):
    def test_private_topic_context_requires_bot_mode(self):
        chat = FakeChat()
        disabled = build_chat_context(chat, FakeMessage(42), private_topics_enabled=False)
        enabled = build_chat_context(chat, FakeMessage(42), private_topics_enabled=True)
        self.assertIsNone(disabled.topic_id)
        self.assertFalse(resolve_chat_capabilities(disabled).supports_topics)
        self.assertEqual(enabled.topic_id, 42)
        caps = resolve_chat_capabilities(enabled)
        self.assertTrue(caps.supports_topics)
        self.assertTrue(caps.supports_private_chat_topics)
        self.assertTrue(caps.is_topic_message)
        self.assertFalse(caps.supports_member_moderation)
        self.assertEqual(enabled.scope_key, (777, 42))

    def test_private_compatibility_exposes_only_supported_operations(self):
        ctx = build_chat_context(FakeChat(), private_topics_enabled=True)
        profile = resolve_private_chat_topic_compatibility(ctx)
        self.assertTrue(profile.is_supported)
        self.assertTrue(profile.supports_topic_creation)
        self.assertTrue(profile.supports_topic_editing)
        self.assertTrue(profile.supports_topic_deletion)
        self.assertFalse(profile.supports_topic_closing)
        self.assertFalse(profile.supports_topic_reopening)
        self.assertFalse(profile.supports_topic_listing)

    async def test_create_edit_delete_private_topic(self):
        store, bot = FakeStore(), FakeBot()
        service = ForumTopicService(store, bot)
        chat = FakeChat()
        topic = await service.create_topic(chat, "Work")
        await service.rename_topic(chat, 42, "Work 2")
        await service.delete_topic(chat, 42)
        bot.create_forum_topic.assert_awaited_once_with(chat_id=777, name="Work")
        bot.edit_forum_topic.assert_awaited_once_with(
            chat_id=777, message_thread_id=42, name="Work 2"
        )
        bot.delete_forum_topic.assert_awaited_once_with(
            chat_id=777, message_thread_id=42
        )
        self.assertFalse(store.rows[(777, 42)]["is_active"])

    async def test_private_close_reopen_are_rejected(self):
        service = ForumTopicService(FakeStore(), FakeBot())
        chat = FakeChat()
        with self.assertRaises(ForumTopicError):
            await service.close_topic(chat, 42)
        with self.assertRaises(ForumTopicError):
            await service.reopen_topic(chat, 42)

    async def test_private_topics_disabled_is_fail_closed(self):
        service = ForumTopicService(FakeStore(), FakeBot(enabled=False))
        with self.assertRaises(ForumTopicError):
            await service.create_topic(FakeChat(), "Nope")


def test_phase19_docs_present():
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text()
    assert "Phase 19" in readme
