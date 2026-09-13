"""Phase 13 — production observability and diagnostics.

Bounded, process-local telemetry for operational debugging. Telemetry never
contains credentials and is not part of moderation/application state.
"""
import contextvars
import json
import logging
import time
import uuid
from collections import Counter, deque
from threading import Lock

_request_id = contextvars.ContextVar("ghostea_request_id", default=None)

_SECRET_KEYS = {
    "token", "bot_token", "api_key", "authorization", "password", "secret",
    "supabase_key", "cookie", "set_cookie",
}


def new_request_id(prefix="req"):
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def set_request_id(value):
    return _request_id.set(str(value))


def reset_request_id(token):
    _request_id.reset(token)


def current_request_id():
    return _request_id.get()


def _safe_value(key, value):
    if str(key).lower() in _SECRET_KEYS:
        return None
    if isinstance(value, dict):
        return {
            str(k): _safe_value(k, v)
            for k, v in value.items()
            if str(k).lower() not in _SECRET_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [_safe_value(key, v) for v in value[:50]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, str) and len(value) > 500:
            return value[:500] + "…"
        return value
    return str(value)[:500]


class Observability:
    """Bounded in-process operational event recorder and metric aggregator."""

    def __init__(self, max_events=2000):
        self.max_events = max(100, int(max_events))
        self._events = deque(maxlen=self.max_events)
        self._counts = Counter()
        self._durations = {}
        self._lock = Lock()

    def emit(self, event, *, level="INFO", **fields):
        safe = {}
        for key, value in fields.items():
            if str(key).lower() in _SECRET_KEYS:
                continue
            safe_value = _safe_value(key, value)
            if safe_value is not None:
                safe[key] = safe_value
        record = {
            "ts": time.time(),
            "event": str(event),
            "level": str(level).upper(),
            "request_id": current_request_id(),
            **safe,
        }
        with self._lock:
            self._events.append(record)
            self._counts[str(event)] += 1
        logging.getLogger("Ghostea").log(
            getattr(logging, str(level).upper(), logging.INFO),
            "obs event=%s request_id=%s fields=%s",
            record["event"], record["request_id"], safe,
        )
        return record

    def observe_duration(self, metric, seconds, *, count=True):
        """Record bounded aggregate latency statistics, never raw samples."""
        try:
            value = max(0.0, float(seconds))
        except (TypeError, ValueError):
            return
        name = str(metric)[:80]
        with self._lock:
            item = self._durations.setdefault(
                name, {"count": 0, "total_ms": 0.0, "max_ms": 0.0}
            )
            if count:
                item["count"] += 1
            ms = value * 1000.0
            item["total_ms"] += ms
            item["max_ms"] = max(item["max_ms"], ms)

    def snapshot(self, limit=100):
        limit = max(1, min(int(limit), self.max_events))
        with self._lock:
            events = list(self._events)[-limit:]
            counts = dict(self._counts)
            durations = {
                key: {
                    **value,
                    "avg_ms": (
                        value["total_ms"] / value["count"]
                        if value["count"] else 0.0
                    ),
                }
                for key, value in self._durations.items()
            }
        return {
            "events": events,
            "counts": counts,
            "durations": durations,
            "buffer_size": len(events),
        }


def install_context_logger():
    """Install a LogRecordFactory adding request_id without changing formats."""
    old = logging.getLogRecordFactory()

    def factory(*args, **kwargs):
        record = old(*args, **kwargs)
        record.request_id = current_request_id() or "-"
        return record

    logging.setLogRecordFactory(factory)


OBSERVABILITY = Observability()
