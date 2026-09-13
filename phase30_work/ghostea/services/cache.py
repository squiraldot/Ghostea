"""Phase 30 — bounded process-local TTL cache primitives.

Caches are performance accelerators only. Callers must keep authoritative state
in the database and invalidate entries after successful writes. The cache is
bounded to prevent a large number of Telegram chats/topics from turning into an
unbounded memory leak.
"""
from __future__ import annotations

from collections import OrderedDict
from threading import RLock
from dataclasses import dataclass
import time
from typing import Generic, Hashable, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class CacheStats:
    hits: int = 0
    misses: int = 0
    evictions: int = 0
    entries: int = 0


class TTLCache(Generic[T]):
    """Small LRU + TTL cache with defensive copying delegated to callers."""

    def __init__(self, max_entries: int = 5000, ttl_seconds: float = 10.0, clock=None):
        self.max_entries = max(1, int(max_entries))
        self.ttl_seconds = max(0.1, float(ttl_seconds))
        self._clock = clock or time.monotonic
        self._items: OrderedDict[Hashable, tuple[float, T]] = OrderedDict()
        self._hits = self._misses = self._evictions = 0
        self._lock = RLock()

    def get(self, key: Hashable):
        with self._lock:
            item = self._items.get(key)
            now = self._clock()
            if item is None:
                self._misses += 1
                return None
            expires_at, value = item
            if expires_at <= now:
                self._items.pop(key, None)
                self._misses += 1
                return None
            self._items.move_to_end(key)
            self._hits += 1
            return value

    def set(self, key: Hashable, value: T, ttl_seconds: float | None = None):
        ttl = self.ttl_seconds if ttl_seconds is None else max(0.1, float(ttl_seconds))
        with self._lock:
            self._items[key] = (self._clock() + ttl, value)
            self._items.move_to_end(key)
            while len(self._items) > self.max_entries:
                self._items.popitem(last=False)
                self._evictions += 1

    def pop(self, key: Hashable, default=None):
        with self._lock:
            item = self._items.pop(key, None)
            return default if item is None else item[1]

    def clear(self):
        with self._lock:
            self._items.clear()

    def invalidate_prefix(self, prefix: str):
        with self._lock:
            for key in list(self._items):
                if isinstance(key, str) and key.startswith(prefix):
                    self._items.pop(key, None)

    def keys(self):
        with self._lock:
            return list(self._items.keys())

    def __len__(self):
        with self._lock:
            return len(self._items)

    def stats(self) -> CacheStats:
        with self._lock:
            return CacheStats(self._hits, self._misses, self._evictions, len(self._items))
