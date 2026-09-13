"""Phase H10 — bounded concurrency and duplicate-update protection.

This module contains process-local safety controls only. Durable state remains in
Supabase; these guards prevent duplicate work, lock stampedes, and unbounded
in-memory growth inside one bot process.
"""
import asyncio
import time
from collections import OrderedDict


class UpdateDeduplicator:
    def __init__(self, ttl_seconds=180.0, max_entries=20000):
        self.ttl = float(ttl_seconds)
        self.max_entries = max(100, int(max_entries))
        self._seen = OrderedDict()
        self._lock = asyncio.Lock()

    async def first(self, update_id):
        if update_id is None:
            return True
        now = time.monotonic()
        async with self._lock:
            cutoff = now - self.ttl
            while self._seen:
                key, seen = next(iter(self._seen.items()))
                if seen >= cutoff:
                    break
                self._seen.popitem(last=False)
            key = int(update_id)
            if key in self._seen:
                self._seen.move_to_end(key)
                return False
            self._seen[key] = now
            while len(self._seen) > self.max_entries:
                self._seen.popitem(last=False)
            return True

    async def clear(self):
        async with self._lock:
            self._seen.clear()


class ConcurrencyGate:
    """Bound concurrent external operations and serialize keyed mutations."""

    def __init__(self, max_external=32, max_key_locks=20000):
        self.max_external = max(1, int(max_external))
        self._semaphores = {}
        self._key_locks = OrderedDict()
        self._max_key_locks = max(100, int(max_key_locks))
        self._meta_lock = asyncio.Lock()

    def external(self):
        """Async context manager for bounded external I/O."""
        loop = asyncio.get_running_loop()
        sem = self._semaphores.get(loop)
        if sem is None:
            sem = asyncio.Semaphore(self.max_external)
            self._semaphores[loop] = sem
        return _SemaphoreContext(sem)

    async def keyed(self, key):
        key = tuple(key) if isinstance(key, (tuple, list)) else key
        async with self._meta_lock:
            lock = self._key_locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._key_locks[key] = lock
            self._key_locks.move_to_end(key)
            while len(self._key_locks) > self._max_key_locks:
                old_key, old_lock = next(iter(self._key_locks.items()))
                if old_lock.locked():
                    self._key_locks.move_to_end(old_key)
                    break
                self._key_locks.popitem(last=False)
        return _LockContext(lock)

    async def clear(self):
        async with self._meta_lock:
            self._semaphores.clear()
            self._key_locks = OrderedDict(
                (k, v) for k, v in self._key_locks.items() if v.locked()
            )


class _SemaphoreContext:
    def __init__(self, sem): self.sem = sem
    async def __aenter__(self):
        await self.sem.acquire()
    async def __aexit__(self, exc_type, exc, tb):
        self.sem.release()


class _LockContext:
    def __init__(self, lock): self.lock = lock
    async def __aenter__(self):
        await self.lock.acquire()
    async def __aexit__(self, exc_type, exc, tb):
        self.lock.release()
