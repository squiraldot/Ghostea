import asyncio

from ghostea.services.chat_context import build_chat_context
from ghostea.storage.phase3_store import Phase3Store


class DB:
    def __init__(self):
        self.rows = []
    def upsert(self, table, payload):
        self.rows.append((table, payload))
        return [payload]
    def select(self, table, query):
        return []


def test_touch_chat_persists_visibility():
    store = Phase3Store(DB())
    chat = type("C", (), {
        "id": -100,
        "type": "supergroup",
        "title": "Public",
        "username": "public_group",
        "is_forum": True,
    })()
    context = build_chat_context(chat)
    asyncio.run(store.touch_chat(context))
    assert store.db.rows[-1][1]["visibility"] == "public"
    assert store.db.rows[-1][1]["is_forum"] is True
