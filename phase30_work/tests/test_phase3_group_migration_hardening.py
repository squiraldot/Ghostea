import asyncio
from ghostea.services.chat_migration_service import ChatMigrationService, CHAT_SCOPED_TABLES


class FakeDB:
    def __init__(self, rows=None):
        self.data = {k: [dict(x) for x in v] for k, v in (rows or {}).items()}

    def select(self, table, query):
        rows = [dict(r) for r in self.data.get(table, [])]
        for key, value in query.items():
            if key in ("limit", "order"):
                continue
            op, raw = str(value).split(".", 1)
            if op == "eq":
                rows = [r for r in rows if str(r.get(key)) == raw]
        return rows[: int(query.get("limit", len(rows) or 1))]

    def update(self, table, payload, query):
        for row in self.data.get(table, []):
            if all(str(row.get(k)) == str(v).split(".", 1)[1] for k, v in query.items()):
                row.update(payload)
        return [dict(r) for r in self.data.get(table, [])]

    def delete(self, table, query):
        kept = []
        for row in self.data.get(table, []):
            if all(str(row.get(k)) != str(v).split(".", 1)[1] for k, v in query.items()):
                kept.append(row)
        self.data[table] = kept
        return kept

    def upsert(self, table, payload):
        rows = self.data.setdefault(table, [])
        keys = {"ghostea_chat_migrations": ("old_chat_id", "new_chat_id"), "ghostea_chat_registry": ("chat_id",)}.get(table)
        if keys:
            for i, row in enumerate(rows):
                if all(row.get(k) == payload.get(k) for k in keys):
                    rows[i] = dict(payload)
                    return [rows[i]]
        rows.append(dict(payload))
        return [dict(payload)]


class Store:
    def __init__(self, db): self.db = db
    async def _call(self, fn, *args, **kwargs): return fn(*args, **kwargs)


def test_migration_handles_large_telegram_ids_and_moves_all_scoped_rows():
    old_id = -1001234567890123
    new_id = -1009876543210987
    rows = {
        "ghostea_chat_registry": [{"chat_id": old_id, "chat_type": "group", "visibility": "private", "is_forum": False}],
        **{table: [{"chat_id": old_id, "marker": table}] for table in CHAT_SCOPED_TABLES},
    }
    db = FakeDB(rows)
    result = asyncio.run(ChatMigrationService(Store(db)).migrate(old_id, new_id))
    assert result["status"] == "completed"
    for table in ("ghostea_chat_registry", *CHAT_SCOPED_TABLES):
        assert all(r["chat_id"] == new_id for r in db.data[table])


def test_migration_blocks_existing_target_state_without_overwriting_it():
    old_id, new_id = -1001, -1002
    db = FakeDB({
        "ghostea_chat_registry": [{"chat_id": old_id}, {"chat_id": new_id}],
        "ghostea_group_settings": [{"chat_id": old_id}, {"chat_id": new_id, "max_warnings": 9}],
    })
    try:
        asyncio.run(ChatMigrationService(Store(db)).migrate(old_id, new_id))
    except RuntimeError as exc:
        assert "target chat already has data" in str(exc)
    else:
        raise AssertionError("migration should have been blocked")
    assert db.data["ghostea_group_settings"][1]["max_warnings"] == 9


def test_migration_rejects_invalid_or_same_ids_before_state_changes():
    service = ChatMigrationService(Store(FakeDB()))
    for old_id, new_id in [(1, 1), (0, 2), ("bad", 2)]:
        try:
            asyncio.run(service.migrate(old_id, new_id))
        except ValueError:
            pass
        else:
            raise AssertionError("invalid migration ids must fail closed")
