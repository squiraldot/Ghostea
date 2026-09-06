import unittest
from unittest.mock import AsyncMock

from ghostea.services.chat_context import build_chat_context
from ghostea.services.chat_capabilities import resolve_chat_capabilities, resolve_forum_compatibility
from ghostea.services.forum_topic_service import ForumTopicService, ForumTopicError, GENERAL_TOPIC_ID


class FakeChat:
    def __init__(self, chat_id=-100, is_forum=True):
        self.id = chat_id
        self.type = "supergroup"
        self.title = "Forum"
        self.username = None
        self.is_forum = is_forum


class FakeMember:
    status = "administrator"
    can_manage_topics = True
    can_delete_messages = True
    can_restrict_members = True


class FakeTopic:
    def __init__(self, name="Help", topic_id=123):
        self.name = name
        self.message_thread_id = topic_id


class FakeStore:
    def __init__(self):
        self.rows = {}
        self.upserts = []

    async def list_topics(self, *args, **kwargs):
        return list(self.rows.values())

    async def get_topic(self, chat_id, topic_id):
        return self.rows.get((int(chat_id), int(topic_id)))

    async def upsert_topic_lifecycle(self, chat_id, topic_id, **kwargs):
        row = {"chat_id": int(chat_id), "topic_id": int(topic_id), **kwargs}
        self.rows[(int(chat_id), int(topic_id))] = row
        self.upserts.append(row)
        return row


class FakeBot:
    def __init__(self):
        self.create_forum_topic = AsyncMock(return_value=FakeTopic())
        self.edit_forum_topic = AsyncMock()
        self.edit_general_forum_topic = AsyncMock()
        self.close_forum_topic = AsyncMock()
        self.close_general_forum_topic = AsyncMock()
        self.reopen_forum_topic = AsyncMock()
        self.reopen_general_forum_topic = AsyncMock()
        self.delete_forum_topic = AsyncMock()
        self.get_me = AsyncMock(return_value=type("Me", (), {"id": 99})())


class FakePermChat(FakeChat):
    async def get_member(self, user_id):
        return FakeMember()


class Phase15ForumTests(unittest.IsolatedAsyncioTestCase):
    def test_forum_capability_contract(self):
        ctx = build_chat_context(FakeChat())
        caps = resolve_chat_capabilities(ctx)
        profile = resolve_forum_compatibility(caps)
        self.assertTrue(profile.is_supported)
        self.assertTrue(profile.supports_topic_creation)
        self.assertTrue(profile.supports_topic_editing)
        self.assertTrue(profile.supports_topic_closing)
        self.assertTrue(profile.supports_topic_reopening)
        self.assertTrue(profile.supports_topic_deletion)
        self.assertTrue(profile.supports_topic_scoped_moderation)

    def test_non_forum_is_rejected(self):
        ctx = build_chat_context(FakeChat(is_forum=False))
        self.assertFalse(resolve_forum_compatibility(resolve_chat_capabilities(ctx)).is_supported)

    async def test_create_persists_topic(self):
        store, bot = FakeStore(), FakeBot()
        service = ForumTopicService(store, bot)
        topic = await service.create_topic(FakePermChat(), "Help")
        bot.create_forum_topic.assert_awaited_once()
        self.assertEqual(topic.message_thread_id, 123)
        self.assertEqual(store.rows[(-100, 123)]["name"], "Help")

    async def test_lifecycle_operations(self):
        store, bot = FakeStore(), FakeBot()
        service = ForumTopicService(store, bot)
        chat = FakePermChat()
        await service.rename_topic(chat, 123, "New")
        await service.close_topic(chat, 123)
        await service.reopen_topic(chat, 123)
        await service.delete_topic(chat, 123)
        bot.edit_forum_topic.assert_awaited_once()
        bot.close_forum_topic.assert_awaited_once()
        bot.reopen_forum_topic.assert_awaited_once()
        bot.delete_forum_topic.assert_awaited_once()
        self.assertFalse(store.rows[(-100, 123)]["is_active"])

    async def test_general_topic_cannot_be_deleted(self):
        service = ForumTopicService(FakeStore(), FakeBot())
        with self.assertRaises(ForumTopicError):
            await service.delete_topic(FakePermChat(), GENERAL_TOPIC_ID)

    async def test_topic_title_validation(self):
        service = ForumTopicService(FakeStore(), FakeBot())
        with self.assertRaises(ForumTopicError):
            await service.create_topic(FakePermChat(), "")
        with self.assertRaises(ForumTopicError):
            await service.create_topic(FakePermChat(), "x" * 129)


if __name__ == "__main__":
    unittest.main()
