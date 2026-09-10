import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from ghostea.services.resource_publishing import ResourcePublishingService
from ghostea.services.upload_workflow import UploadMode


class Store:
    def __init__(self):
        self.rows = {}
        self.resource = None

    async def claim_upload_for_publish(self, sid, uid):
        row = self.rows[sid]
        row["state"] = "publishing"
        return row

    async def get_resource_by_session(self, sid): return self.resource
    async def create_resource(self, row): self.resource = row; return row
    async def update_upload_session(self, sid, **changes): self.rows[sid].update(changes)

    async def get_topic(self, chat_id, topic_id): return None
    async def list_topics(self, chat_id, include_inactive=False, limit=200):
        return [{"chat_id": chat_id, "topic_id": 7, "name": "Closed", "is_active": True, "is_closed": True, "is_hidden": False}]


class Workflow:
    async def _revalidate_target(self, session, user_id):
        return SimpleNamespace(id=-100, type="supergroup", is_forum=True, send_message=AsyncMock(), send_photo=AsyncMock())
    async def get(self, *args, **kwargs): raise AssertionError
    def _as_session(self, row): return SimpleNamespace(**row)


class Topics:
    def __init__(self): self.reopen_topic = AsyncMock()
    async def list_topics(self, chat, include_inactive=False, limit=200):
        return [{"chat_id": chat.id, "topic_id": 7, "name": "Closed", "is_active": True, "is_closed": True, "is_hidden": False}]


class Phase7ClosedTopicTests(unittest.IsolatedAsyncioTestCase):
    async def test_closed_topic_is_reopened_before_publish(self):
        store = Store()
        store.rows["s1"] = {
            "session_id": "s1", "user_id": 42, "chat_id": -100, "topic_id": 7,
            "mode": UploadMode.RESOURCE.value, "state": "ready",
            "payload": {"source": {"kind": "url", "url": "https://example.com"}, "caption": "C", "description": "D"},
        }
        topics = Topics()
        bot = SimpleNamespace(
            get_me=AsyncMock(return_value=SimpleNamespace(id=900)),
            get_chat_member=AsyncMock(return_value=SimpleNamespace(status="administrator", can_manage_topics=True)),
        )
        service = ResourcePublishingService(store, Workflow(), None, topics, bot)
        result = await service.publish("s1", 42)
        topics.reopen_topic.assert_awaited_once()
        self.assertTrue(result)

    async def test_hidden_topic_is_rejected(self):
        store = Store()
        store.rows["s1"] = {
            "session_id": "s1", "user_id": 42, "chat_id": -100, "topic_id": 7,
            "mode": UploadMode.RESOURCE.value, "state": "ready",
            "payload": {"source": {"kind": "url", "url": "https://example.com"}, "caption": "C", "description": "D"},
        }
        class HiddenTopics(Topics):
            async def list_topics(self, chat, include_inactive=False, limit=200):
                return [{"chat_id": chat.id, "topic_id": 7, "name": "Hidden", "is_active": True, "is_closed": True, "is_hidden": True}]
        bot = SimpleNamespace(
            get_me=AsyncMock(return_value=SimpleNamespace(id=900)),
            get_chat_member=AsyncMock(return_value=SimpleNamespace(status="administrator", can_manage_topics=True)),
        )
        service = ResourcePublishingService(store, Workflow(), None, HiddenTopics(), bot)
        with self.assertRaises(Exception):
            await service.publish("s1", 42)


if __name__ == "__main__": unittest.main()
