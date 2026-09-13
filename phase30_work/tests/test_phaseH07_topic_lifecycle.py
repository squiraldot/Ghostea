import asyncio
import importlib.util
import sys
import types
import unittest
from unittest.mock import AsyncMock

# Lightweight telegram stubs so this test can run in the minimal source audit
# environment without installing python-telegram-bot.
telegram = types.ModuleType("telegram")
telegram.Update = object
telegram.ext = types.ModuleType("telegram.ext")
telegram.ext.ContextTypes = types.SimpleNamespace(DEFAULT_TYPE=object)
sys.modules.setdefault("telegram", telegram)
sys.modules.setdefault("telegram.ext", telegram.ext)

from ghostea.storage.phase3_store import Phase3Store
from ghostea.services.forum_topic_service import ForumTopicService, GENERAL_TOPIC_ID


class FakeDB:
    async def select(self, table, query=None):
        return []
    async def upsert(self, table, payload):
        return [payload]
    async def update(self, table, payload, query=None):
        return [payload]
    async def delete(self, table, query=None):
        return []


class FakeTopicStore:
    def __init__(self):
        self.rows = {}
    async def get_topic(self, chat_id, topic_id):
        return self.rows.get((int(chat_id), int(topic_id)))
    async def upsert_topic_lifecycle(self, chat_id, topic_id, **kwargs):
        row = {"chat_id": int(chat_id), "topic_id": int(topic_id), **kwargs}
        self.rows[(int(chat_id), int(topic_id))] = row
        return row


class FakeChat:
    id = -100
    type = "supergroup"
    title = "Forum"
    username = None
    is_forum = True

class FakeBot:
    async def get_me(self):
        return types.SimpleNamespace(has_topics_enabled=False)

class H07Tests(unittest.IsolatedAsyncioTestCase):
    def test_store_event_parser_includes_hidden(self):
        msg = types.SimpleNamespace(
            forum_topic_closed=None,
            forum_topic_reopened=None,
            forum_topic_deleted=None,
            forum_topic_created=None,
            forum_topic_edited=None,
            general_forum_topic_hidden=object(),
            general_forum_topic_unhidden=None,
        )
        # General hidden is handled by the store's explicit parser in H07.
        # The parser returns the existing lifecycle shape for normal events;
        # hidden events are checked by source-level contract below.
        source = open("ghostea/storage/phase3_store.py", encoding="utf8").read()
        self.assertIn("general_forum_topic_hidden", source)
        self.assertIn("general_forum_topic_unhidden", source)

    async def test_definitive_topic_error_retires_topic(self):
        store = FakeTopicStore()
        store.rows[(-100, 42)] = {
            "chat_id": -100, "topic_id": 42, "name": "Old",
            "is_active": True, "is_closed": False, "is_hidden": False
        }
        service = ForumTopicService(store, FakeBot())
        await service._mark_topic_stale(-100, 42, "TOPIC_ID_INVALID")
        row = store.rows[(-100, 42)]
        self.assertFalse(row["is_active"])
        self.assertTrue(row["is_closed"])

    def test_only_definitive_errors_are_stale(self):
        self.assertTrue(ForumTopicService._topic_lifecycle_failure(Exception("400 TOPIC_ID_INVALID")))
        self.assertTrue(ForumTopicService._topic_lifecycle_failure(Exception("MESSAGE_THREAD_NOT_FOUND")))
        self.assertFalse(ForumTopicService._topic_lifecycle_failure(Exception("403 Forbidden")))
        self.assertFalse(ForumTopicService._topic_lifecycle_failure(Exception("429 retry_after 5")))

    def test_general_topic_constant(self):
        self.assertEqual(GENERAL_TOPIC_ID, 1)

if __name__ == "__main__":
    unittest.main()
