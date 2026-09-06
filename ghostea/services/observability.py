"""Phase H12 — structured production observability.

Observability is deliberately side-effect-light: it records operational events
without changing moderation decisions. Sensitive credentials are never stored.
"""
import contextvars
import json
import logging
import time
import uuid
from collections import Counter, deque
from threading import Lock

_request_id = contextvars.ContextVar("ghostea_request_id", default=None)


def new_request_id(prefix="req"):
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def set_request_id(value):
    return _request_id.set(str(value))


def reset_request_id(token):
    _request_id.reset(token)


def current_request_id():
    return _request_id.get()


class Observability:
    """Bounded in-process operational event recorder."""

    def __init__(self, max_events=2000):
        self.max_events = max(100, int(max_events))
        self._events = deque(maxlen=self.max_events)
        self._counts = Counter()
        self._lock = Lock()

    def emit(self, event, *, level="INFO", **fields):
        safe = {}
        for key, value in fields.items():
            if key.lower() in {"token", "bot_token", "api_key", "authorization", "password", "secret"}:
                continue
            if value is not None:
                safe[key] = value
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

    def snapshot(self, limit=100):
        limit = max(1, min(int(limit), self.max_events))
        with self._lock:
            events = list(self._events)[-limit:]
            counts = dict(self._counts)
        return {"events": events, "counts": counts, "buffer_size": len(events)}


def install_context_logger():
    """Install a LogRecordFactory adding request_id without changing formats."""
    old = logging.getLogRecordFactory()
    def factory(*args, **kwargs):
        record = old(*args, **kwargs)
        record.request_id = current_request_id() or "-"
        return record
    logging.setLogRecordFactory(factory)


OBSERVABILITY = Observability()
