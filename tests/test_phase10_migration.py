import asyncio
from pathlib import Path

from ghostea.services.chat_migration_service import ChatMigrationService, CHAT_SCOPED_TABLES
from ghostea.services.protection_service import ProtectionService


class FakeDB:
    def __init__(self, rows=None):
        self.data = {k: [dict(x) for x in v] for k, v in (rows or {}).items()}
    def select(self, table, query):
        rows = self.data.get(table, [])
        def val(q):
            return int(str(q).split(".", 1)[1])
        if "chat_id" in query:
            cid = val(query["chat_id"])
            rows = [r for r in rows if int(r.get("chat_id", 0)) == cid]
        return rows[: int(query.get("limit", len(rows) or 1))]
    def update(self, table, payload, query):
        cid = int(str(query["chat_id"]).split(".",1)[1])
        out=[]
        for r in self.data.get(table, []):
            if int(r.get("chat_id",0)) == cid:
                r.update(payload)
            out.append(r)
        self.data[table]=out
        return out
    def upsert(self, table, payload):
        rows=self.data.setdefault(table, [])
        for i,r in enumerate(rows):
            if table=="ghostea_chat_migrations" and r.get("old_chat_id")==payload["old_chat_id"] and r.get("new_chat_id")==payload["new_chat_id"]:
                rows[i]=payload; return [payload]
        rows.append(payload); return [payload]
    def delete(self, table, query):
        cid=int(str(query["chat_id"]).split(".",1)[1])
        self.data[table]=[r for r in self.data.get(table,[]) if int(r.get("chat_id",0)) != cid]
        return self.data[table]


class Store:
    def __init__(self, db):
        self.db=db
    async def _call(self, fn, *args, **kwargs):
        return fn(*args, **kwargs)


def test_chat_migration_moves_persistent_state():
    db=FakeDB({
        "ghostea_chat_registry":[{"chat_id":-10,"chat_type":"group","is_forum":False}],
        "ghostea_group_settings":[{"chat_id":-10,"max_warnings":3}],
        "ghostea_warnings":[{"chat_id":-10,"user_id":5,"count":2}],
    })
    service=ChatMigrationService(Store(db))
    result=asyncio.run(service.migrate(-10,-20))
    assert result["status"]=="completed"
    assert db.data["ghostea_group_settings"][0]["chat_id"] == -20
    assert db.data["ghostea_warnings"][0]["chat_id"] == -20
    assert db.data["ghostea_chat_registry"][0]["chat_id"] == -20
    assert db.data["ghostea_chat_registry"][0]["chat_type"] == "supergroup"


def test_chat_migration_is_collision_safe():
    db=FakeDB({
        "ghostea_group_settings":[{"chat_id":-20,"max_warnings":9}],
        "ghostea_warnings":[{"chat_id":-10,"user_id":5,"count":2}],
    })
    service=ChatMigrationService(Store(db))
    try:
        asyncio.run(service.migrate(-10,-20))
        assert False, "expected collision"
    except RuntimeError as exc:
        assert "target chat already has data" in str(exc)
    assert db.data["ghostea_warnings"][0]["chat_id"] == -10


def test_protection_state_is_discarded_after_migration():
    p=ProtectionService(type("L",(),{"items":[]})(), type("L",(),{"items":[]})(), 8, 6)
    p.register_message(-10, 5, 8, 6, scope_key=(-10, None))
    p.register_join(-10, 5, 20, 8)
    p.discard_chat(-10)
    assert not p._messages
    assert not p._joins


def test_phase10_table_list_has_topic_state():
    assert "ghostea_topic_registry" in CHAT_SCOPED_TABLES
    assert "ghostea_topic_settings" in CHAT_SCOPED_TABLES


def test_database_has_migration_journal():
    sql=(Path(__file__).resolve().parents[1]/"database.sql").read_text()
    assert "ghostea_chat_migrations" in sql
    assert "completed_tables" in sql
