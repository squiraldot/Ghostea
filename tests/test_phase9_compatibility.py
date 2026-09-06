import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

from ghostea.services.chat_context import ChatContext
from ghostea.services.scope_policy import CHAT_WIDE, TOPIC_AWARE, FORUM_ONLY, get_service_scope
from ghostea.services.protection_service import ProtectionService
from ghostea.storage.phase3_store import Phase3Store


def ctx(chat_id, chat_type="supergroup", forum=False, topic_id=None):
    return ChatContext(chat_id, chat_type, "test", None, chat_type == "group", chat_type == "supergroup", forum, topic_id)


def test_environment_matrix():
    group = ctx(1, "group", False, 99)
    supergroup = ctx(2, "supergroup", False, 99)
    forum = ctx(3, "supergroup", True, 99)
    assert group.scope_key == (1, None)
    assert supergroup.scope_key == (2, None)
    assert forum.scope_key == (3, 99)
    assert group.service_scope_key("warnings") == (1, None)
    assert forum.service_scope_key("warnings") == (3, None)
    assert forum.service_scope_key("flood") == (3, 99)


def test_all_declared_scopes_are_known():
    expected = {CHAT_WIDE, TOPIC_AWARE, FORUM_ONLY}
    for name in ("warnings", "reputation", "verification", "anti_raid", "welcome", "user_management", "rbac", "security_locks", "custom_filters", "settings", "joins", "moderation", "flood", "repeat_spam", "moderation_logs", "analytics", "risk", "topic_registry"):
        assert get_service_scope(name).mode in expected


def test_protection_topic_isolation_and_chat_wide_join():
    p = ProtectionService(type("L", (), {"items": []})(), type("L", (), {"items": []})(), 10, 3)
    assert p.register_message(10, 5, 10, 3, scope_key=(10, 100)) is False
    assert p.register_message(10, 5, 10, 3, scope_key=(10, 100)) is False
    assert p.register_message(10, 5, 10, 3, scope_key=(10, 200)) is False
    assert p.register_repeated_message(10, 5, "hello", 60, 3, scope_key=(10, 100)) is False
    assert p.register_repeated_message(10, 5, "hello", 60, 3, scope_key=(10, 100)) is False
    assert p.register_repeated_message(10, 5, "hello", 60, 3, scope_key=(10, 100)) is True
    assert p.register_repeated_message(10, 5, "hello", 60, 3, scope_key=(10, 200)) is False


def test_topic_lifecycle_preserves_name_and_closed_state():
    class DB:
        def __init__(self): self.rows = [{"chat_id": 3, "topic_id": 9, "name": "Support", "is_active": True, "is_closed": False}]
        def select(self, table, query): return list(self.rows)
        def upsert(self, table, row): self.rows[:] = [row]; return [row]
    store = Phase3Store(DB())
    message = type("M", (), {"forum_topic_closed": object(), "forum_topic_created": None, "forum_topic_edited": None, "forum_topic_reopened": None, "forum_topic_deleted": None})()
    asyncio.run(store.touch_topic(ctx(3, forum=True, topic_id=9), message))
    assert store.db.rows[0]["name"] == "Support"
    assert store.db.rows[0]["is_closed"] is True
