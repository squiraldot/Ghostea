import asyncio
from pathlib import Path

from ghostea.services.chat_migration_service import ChatMigrationService


class FakeDB:
    def __init__(self, rows=None):
        self.data = {k: [dict(x) for x in v] for k, v in (rows or {}).items()}

    def select(self, table, query):
        rows = [dict(r) for r in self.data.get(table, [])]
        for key, value in query.items():
            if key in ("limit", "order"):
                continue
            if "." in str(value):
                op, raw = str(value).split(".", 1)
                if op == "eq":
                    rows = [r for r in rows if str(r.get(key)) == raw]
        return rows[: int(query.get("limit", len(rows) or 1))]

    def update(self, table, payload, query):
        out = []
        for r in self.data.get(table, []):
            ok = True
            for key, value in query.items():
                if str(value).startswith("eq."):
                    ok &= str(r.get(key)) == str(value).split(".", 1)[1]
            if ok:
                r.update(payload)
            out.append(r)
        self.data[table] = out
        return out

    def upsert(self, table, payload):
        rows = self.data.setdefault(table, [])
        keys = {
            "ghostea_chat_migrations": ("old_chat_id", "new_chat_id"),
            "ghostea_chat_registry": ("chat_id",),
        }.get(table)
        if keys:
            for i, row in enumerate(rows):
                if all(row.get(k) == payload.get(k) for k in keys):
                    rows[i] = dict(payload)
                    return [rows[i]]
        rows.append(dict(payload))
        return [dict(payload)]


class Store:
    def __init__(self, db):
        self.db = db

    async def _call(self, fn, *args, **kwargs):
        return fn(*args, **kwargs)


def ctx(chat_id=-20, chat_type="supergroup", username=None, visibility="private", is_forum=False):
    return type("Context", (), {
        "chat_id": chat_id,
        "chat_type": chat_type,
        "title": "Test",
        "username": username,
        "visibility": visibility,
        "is_forum": is_forum,
        "is_supported": True,
    })()


def test_interrupted_migration_can_resume():
    db = FakeDB({
        "ghostea_chat_migrations": [{
            "old_chat_id": -10, "new_chat_id": -20, "status": "running",
            "completed_tables": ["ghostea_group_settings"],
        }],
        "ghostea_group_settings": [{"chat_id": -20, "max_warnings": 3}],
        "ghostea_warnings": [{"chat_id": -10, "user_id": 5, "count": 2}],
    })
    service = ChatMigrationService(Store(db))
    result = asyncio.run(service.recover_migration(-10, -20))
    assert result["status"] == "completed"
    assert db.data["ghostea_warnings"][0]["chat_id"] == -20


def test_reconcile_refreshes_identity_and_forum_state():
    db = FakeDB({
        "ghostea_chat_registry": [{
            "chat_id": -20, "chat_type": "group", "username": None,
            "visibility": "private", "is_forum": False,
        }],
        "ghostea_topic_registry": [{
            "chat_id": -20, "topic_id": 10, "name": "Old",
            "is_active": True, "is_closed": False,
        }],
    })
    service = ChatMigrationService(Store(db))
    result = asyncio.run(service.reconcile_chat(
        ctx(username="ghostea", visibility="public", is_forum=True),
        reason="post_migration",
    ))
    assert result["changed"] is True
    assert db.data["ghostea_chat_registry"][0]["chat_type"] == "supergroup"
    assert db.data["ghostea_chat_registry"][0]["is_forum"] is True


def test_reconcile_retires_topics_when_forum_flag_disappears():
    db = FakeDB({
        "ghostea_chat_registry": [{
            "chat_id": -20, "chat_type": "supergroup", "is_forum": True,
            "username": None, "visibility": "private",
        }],
        "ghostea_topic_registry": [{
            "chat_id": -20, "topic_id": 10, "is_active": True, "is_closed": False,
        }],
    })
    service = ChatMigrationService(Store(db))
    asyncio.run(service.reconcile_chat(ctx(is_forum=False), reason="lifecycle"))
    assert db.data["ghostea_topic_registry"][0]["is_active"] is False
    assert db.data["ghostea_topic_registry"][0]["is_closed"] is True


def test_phase18_schema_has_lifecycle_support():
    sql = (Path(__file__).resolve().parents[1] / "database.sql").read_text()
    assert "ghostea_chat_migrations" in sql
    assert "completed_tables" in sql
