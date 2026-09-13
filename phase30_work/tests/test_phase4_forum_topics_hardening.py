import unittest
from unittest.mock import AsyncMock

from ghostea.services.chat_context import build_chat_context
from ghostea.services.forum_topic_service import (
    ForumTopicError, ForumTopicService, GENERAL_TOPIC_ID,
)


class Chat:
    def __init__(self, chat_id=-100, is_forum=True):
        self.id = chat_id
        self.type = "supergroup"
        self.title = "Forum"
        self.username = None
        self.is_forum = is_forum


class Message:
    def __init__(self, thread=None):
        self.message_thread_id = thread


class Store:
    def __init__(self):
        self.rows = {}

    async def list_topics(self, chat_id, include_inactive=False, limit=200):
        rows = [r for (cid, _), r in self.rows.items() if cid == int(chat_id)]
        if not include_inactive:
            rows = [r for r in rows if r.get("is_active", True)]
        return rows[:limit]

    async def get_topic(self, chat_id, topic_id):
        return self.rows.get((int(chat_id), int(topic_id)))

    async def upsert_topic_lifecycle(self, chat_id, topic_id, **kwargs):
        row = {"chat_id": int(chat_id), "topic_id": int(topic_id), **kwargs}
        self.rows[(int(chat_id), int(topic_id))] = row
        return row


class Bot:
    def __init__(self):
        self.get_me = AsyncMock(return_value=type("Me", (), {"id": 99})())
        self.create_forum_topic = AsyncMock(return_value=type("T", (), {"name": "Help", "message_thread_id": 123})())


class Phase4ForumHardeningTests(unittest.IsolatedAsyncioTestCase):
    def test_general_topic_maps_to_id_one_without_thread_id(self):
        ctx = build_chat_context(Chat(), Message())
        self.assertEqual(ctx.topic_id, GENERAL_TOPIC_ID)
        self.assertTrue(ctx.is_topic_message)
        self.assertEqual(ctx.scope_key, (-100, GENERAL_TOPIC_ID))

    def test_normal_supergroup_without_forum_stays_chat_scoped(self):
        ctx = build_chat_context(Chat(is_forum=False), Message())
        self.assertIsNone(ctx.topic_id)
        self.assertFalse(ctx.is_topic_message)

    def test_topic_ids_are_chat_scoped(self):
        store = Store()
        store.rows[(-100, 77)] = {"chat_id": -100, "topic_id": 77, "name": "A", "is_active": True}
        store.rows[(-200, 77)] = {"chat_id": -200, "topic_id": 77, "name": "B", "is_active": True}
        self.assertEqual(store.rows[(-100, 77)]["name"], "A")
        self.assertEqual(store.rows[(-200, 77)]["name"], "B")

    async def test_fresh_forum_seeds_general_topic(self):
        store, bot = Store(), Bot()
        service = ForumTopicService(store, bot)
        rows = await service.list_topics(Chat())
        self.assertEqual(rows[0]["topic_id"], GENERAL_TOPIC_ID)
        self.assertEqual(rows[0]["name"], "General")

    async def test_selectable_topics_excludes_closed_hidden_deleted(self):
        store, bot = Store(), Bot()
        store.rows.update({
            (-100, 1): {"chat_id": -100, "topic_id": 1, "name": "General", "is_active": True, "is_closed": False, "is_hidden": False},
            (-100, 2): {"chat_id": -100, "topic_id": 2, "name": "Closed", "is_active": True, "is_closed": True, "is_hidden": False},
            (-100, 3): {"chat_id": -100, "topic_id": 3, "name": "Hidden", "is_active": True, "is_closed": False, "is_hidden": True},
            (-100, 4): {"chat_id": -100, "topic_id": 4, "name": "Deleted", "is_active": False, "is_closed": True, "is_hidden": False},
            (-100, 5): {"chat_id": -100, "topic_id": 5, "name": "Open", "is_active": True, "is_closed": False, "is_hidden": False},
        })
        rows = await ForumTopicService(store, bot).list_selectable_topics(Chat())
        self.assertEqual([r["topic_id"] for r in rows], [1, 5])

    async def test_invalid_icon_color_is_rejected_before_telegram_call(self):
        store, bot = Store(), Bot()
        service = ForumTopicService(store, bot)
        with self.assertRaises(ForumTopicError):
            await service.create_topic(Chat(), "Help", icon_color=123)
        bot.create_forum_topic.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
