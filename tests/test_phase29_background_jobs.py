import asyncio
import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ghostea.services.background_jobs import BackgroundJobQueue


class FakeDB:
    def __init__(self):
        self.rows = {}

    def insert(self, table, payload, return_rows=False):
        if payload["job_id"] in self.rows:
            raise RuntimeError("duplicate key")
        row = dict(payload)
        self.rows[row["job_id"]] = row
        return [row] if return_rows else []

    def select(self, table, query):
        rows = list(self.rows.values())
        if "job_id" in query and query["job_id"].startswith("eq."):
            rows = [r for r in rows if r["job_id"] == query["job_id"][3:]]
        if query.get("status", "").startswith("eq."):
            rows = [r for r in rows if r["status"] == query["status"][3:]]
        if query.get("status", "").startswith("in.("):
            values = query["status"][4:-1].split(",")
            rows = [r for r in rows if r["status"] in values]
        if "available_at" in query:
            import datetime
            if query["available_at"].startswith("lte."):
                cutoff = datetime.datetime.fromisoformat(query["available_at"][4:])
                rows = [r for r in rows if datetime.datetime.fromisoformat(r["available_at"]) <= cutoff]
        if query.get("order"):
            rows.sort(key=lambda r: r["available_at"])
        return rows[:int(query.get("limit", len(rows) or 1))]

    def update(self, table, payload, query):
        rows = self.select(table, query)
        for row in rows:
            row.update(payload)
        return rows


class Store:
    def __init__(self):
        self.db = FakeDB()
    async def _call(self, fn, *args, **kwargs):
        return fn(*args, **kwargs)


def test_enqueue_claim_and_retry():
    async def run():
        store = Store()
        q = BackgroundJobQueue(store)
        calls = []
        async def handler(payload):
            calls.append(payload["x"])
            raise RuntimeError("boom")
        q.register("test", handler)
        job = await q.enqueue("test", {"x": 1}, job_id="job-1", max_attempts=2)
        assert job["status"] == "pending"
        claimed = await q._claim_one()
        assert claimed["status"] == "running"
        await q._finish(claimed, error=RuntimeError("boom"))
        row = store.db.rows["job-1"]
        assert row["status"] == "pending"
        assert row["attempts"] == 1
    asyncio.run(run())


def test_success_and_deterministic_duplicate_enqueue():
    async def run():
        store = Store()
        q = BackgroundJobQueue(store)
        q.register("test", lambda payload: None)
        first = await q.enqueue("test", job_id="same")
        second = await q.enqueue("test", job_id="same")
        assert first["job_id"] == second["job_id"]
        assert len(store.db.rows) == 1
    asyncio.run(run())


def test_payload_limit_and_unknown_handler():
    async def run():
        store = Store()
        q = BackgroundJobQueue(store)
        try:
            await q.enqueue("missing")
            assert False
        except ValueError:
            pass
        q.register("test", lambda payload: None)
        old = os.environ.get("GHOSTEA_JOB_PAYLOAD_MAX_BYTES")
        os.environ["GHOSTEA_JOB_PAYLOAD_MAX_BYTES"] = "10"
        # config is imported at module load, so verify serialization remains
        # safe by using the public validation with a monkeypatched module value.
        import ghostea.services.background_jobs as mod
        previous = mod.GHOSTEA_JOB_PAYLOAD_MAX_BYTES
        mod.GHOSTEA_JOB_PAYLOAD_MAX_BYTES = 10
        try:
            try:
                await q.enqueue("test", {"long": "x" * 100})
                assert False
            except ValueError:
                pass
        finally:
            mod.GHOSTEA_JOB_PAYLOAD_MAX_BYTES = previous
            if old is None: os.environ.pop("GHOSTEA_JOB_PAYLOAD_MAX_BYTES", None)
            else: os.environ["GHOSTEA_JOB_PAYLOAD_MAX_BYTES"] = old
    asyncio.run(run())


def test_concurrent_claim_only_one_wins():
    async def run():
        store = Store()
        q1, q2 = BackgroundJobQueue(store), BackgroundJobQueue(store)
        q1.register("test", lambda payload: None); q2.register("test", lambda payload: None)
        await q1.enqueue("test", job_id="race")
        a, b = await asyncio.gather(q1._claim_one(), q2._claim_one())
        assert (a is None) != (b is None)
    asyncio.run(run())

def test_migration_checksum_and_schema_version():
    from ghostea.services.schema_migrations import load_migrations
    migration = (ROOT / "ghostea" / "migrations" / "0011_background_jobs.sql").read_text()
    catalog = {m.version: m for m in load_migrations()}
    assert catalog[11].checksum == "ee22b8a7923e7c811328fc86ae12450c733317bdc8e4b8d8517a62095aa89286"
    assert f"values (11, 'background_jobs', '{catalog[11].checksum}')" in migration
    schema = (ROOT / "database.sql").read_text()
    assert f"values (11, 'background_jobs', '{catalog[11].checksum}')" in schema
    assert "greatest(schema_version, 11)" in schema


def test_psql_runner_is_available_without_psycopg(monkeypatch):
    import ghostea.services.schema_migrations as sm
    calls = {}
    monkeypatch.setattr(sm.shutil, "which", lambda name: "/data/data/com.termux/files/usr/bin/psql")
    def fake_run(cmd, **kwargs):
        calls["cmd"] = cmd
        calls["kwargs"] = kwargs
        return type("Result", (), {"returncode": 0, "stdout": "ok\\n", "stderr": ""})()
    monkeypatch.setattr(sm.subprocess, "run", fake_run)
    result = sm.apply_with_psql("select 1;", "postgresql://user:secret@example/db")
    assert result["applied_via"] == "psql"
    assert calls["cmd"][0].endswith("/psql")
    assert "postgresql://user:secret@example/db" in calls["cmd"]
    assert calls["kwargs"]["input"] == "select 1;"
    assert calls["kwargs"]["check"] is False


def test_psql_status_handles_legacy_db_without_ledger(monkeypatch):
    import ghostea.services.schema_migrations as sm
    responses = iter(["t", "9", "f"])
    monkeypatch.setattr(sm, "_run_psql", lambda *args, **kwargs: next(responses))
    status = sm.migration_status_psql("postgresql://user:secret@example/db")
    assert status["current_version"] == 9
    assert status["pending"] == [10, 11]
    assert status["ledger_exists"] is False
    assert status["ready_to_apply"] is True


def test_psql_status_detects_checksum_drift(monkeypatch):
    import ghostea.services.schema_migrations as sm
    responses = iter(["t", "11", "t", "10|schema_migration_ledger|bad\n11|background_jobs|bad"])
    monkeypatch.setattr(sm, "_run_psql", lambda *args, **kwargs: next(responses))
    status = sm.migration_status_psql("postgresql://user:secret@example/db")
    assert status["checksum_drift"] == [10, 11]
    assert status["ready_to_apply"] is False


def test_psql_migration_path_does_not_need_supabase_credentials(monkeypatch):
    import ghostea.services.schema_migrations as sm
    import scripts.ghostea_migrate as cli
    calls = []
    monkeypatch.setattr(sm, "migration_status_psql", lambda url: {
        "current_version": 9, "latest_version": 11, "pending": [10, 11],
        "ledger_exists": False, "checksum_drift": [], "ready_to_apply": True,
        "bootstrap_required": False,
    })
    monkeypatch.setattr(sm, "apply_with_psql", lambda sql, url: calls.append((sql, url)) or {"applied_via": "psql"})
    monkeypatch.setattr(cli, "migration_status_psql", sm.migration_status_psql)
    monkeypatch.setattr(cli, "apply_with_psql", sm.apply_with_psql)
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:secret@example/db")
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_KEY", raising=False)
    monkeypatch.setattr("sys.argv", ["ghostea_migrate.py", "--apply-psql"])
    assert cli.main() == 0
    assert calls and "Migration 10" in calls[0][0] and "Migration 11" in calls[0][0]

