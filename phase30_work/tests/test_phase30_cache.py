import asyncio
import os
import time
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ghostea.services.cache import TTLCache
from ghostea.storage.phase3_store import Phase3Store


def test_ttl_cache_hits_and_expiry():
    now = [100.0]
    cache = TTLCache(max_entries=2, ttl_seconds=5, clock=lambda: now[0])
    cache.set("a", {"x": 1})
    assert cache.get("a") == {"x": 1}
    now[0] += 5.1
    assert cache.get("a") is None
    stats = cache.stats()
    assert stats.hits == 1
    assert stats.misses == 1


def test_ttl_cache_is_bounded_lru():
    cache = TTLCache(max_entries=2, ttl_seconds=30)
    cache.set("a", 1)
    cache.set("b", 2)
    assert cache.get("a") == 1
    cache.set("c", 3)
    assert cache.get("b") is None
    assert cache.get("a") == 1
    assert cache.get("c") == 3
    assert cache.stats().evictions == 1


def test_store_settings_cache_prevents_duplicate_reads():
    class DB:
        def __init__(self):
            self.calls = 0
        def select(self, table, query):
            self.calls += 1
            return [{"chat_id": 123, "max_warnings": 3}]
    async def run():
        db = DB()
        store = Phase3Store(db)
        a = await store.get_settings(123)
        b = await store.get_settings(123)
        assert a["max_warnings"] == b["max_warnings"] == 3
        assert db.calls == 1
        assert store.cache_stats()["settings"]["hits"] == 1
    asyncio.run(run())


def test_store_invalidation_forces_reload():
    class DB:
        def __init__(self):
            self.calls = 0
        def select(self, table, query):
            self.calls += 1
            return [{"chat_id": 123, "max_warnings": self.calls}]
    async def run():
        db = DB()
        store = Phase3Store(db)
        assert (await store.get_settings(123))["max_warnings"] == 1
        store.invalidate_group_cache(123)
        assert (await store.get_settings(123))["max_warnings"] == 2
        assert db.calls == 2
    asyncio.run(run())


def test_malformed_provider_timeouts_fall_back(monkeypatch):
    monkeypatch.setenv("SUPABASE_HTTP_TIMEOUT_SECONDS", "not-a-number")
    monkeypatch.setenv("SUPABASE_READ_RETRIES", "not-a-number")
    from ghostea.storage.database import SupabaseREST
    provider = SupabaseREST("https://example.supabase.co", "key")
    assert provider.timeout == 15.0
    assert provider.read_retries == 3

def test_dashboard_cache_is_bounded_and_thread_safe():
    from ghostea.web_server import DashboardHandler
    DashboardHandler._cache.clear()
    DashboardHandler._cache.max_entries = 2
    DashboardHandler._put_cache("a", {"v": 1})
    DashboardHandler._put_cache("b", {"v": 2})
    DashboardHandler._put_cache("c", {"v": 3})
    assert DashboardHandler._cached_json("a") is None
    assert DashboardHandler._cached_json("b")["v"] == 2
    assert DashboardHandler._cached_json("c")["v"] == 3
    DashboardHandler._cache.max_entries = 1000
    DashboardHandler._invalidate_cache()
