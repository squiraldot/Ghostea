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
    import hashlib
    migration = (ROOT / "ghostea" / "migrations" / "0011_background_jobs.sql").read_bytes()
    assert hashlib.sha256(migration).hexdigest() == "7d69c9ef246bc233e160ab2d347f35f6ac08d54279d81a31e933828778d88ec0"
    schema = (ROOT / "database.sql").read_text()
    assert "values (11, 'background_jobs'" in schema
    assert "greatest(schema_version, 11)" in schema
