"""Phase H05 — Telegram error and rate-limit policy.

Centralizes classification and bounded retry policy. Destructive/non-idempotent
operations are never blindly retried; safe reads may be retried after a
Telegram retry_after response.
"""
import asyncio
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class TelegramFailure:
    kind: str
    detail: str
    retry_after: int | None = None
    error_code: int | None = None

    @property
    def transient(self):
        return self.kind in {"rate_limited", "network", "timeout", "server"}


class TelegramErrorPolicy:
    """Bounded, non-amplifying policy for Telegram API failures."""

    def __init__(self, max_retries: int = 2, max_retry_after: int = 30):
        self.max_retries = max(0, int(max_retries))
        self.max_retry_after = max(0, int(max_retry_after))
        self._cooldowns: dict[int, float] = {}

    @staticmethod
    def classify(error: Exception) -> TelegramFailure:
        name = error.__class__.__name__
        code = getattr(error, "code", None)
        try:
            code = int(code) if code is not None else None
        except (TypeError, ValueError):
            code = None
        retry_after = getattr(error, "retry_after", None)
        try:
            retry_after = max(0, int(retry_after)) if retry_after is not None else None
        except (TypeError, ValueError):
            retry_after = None
        text = str(error).strip()
        low = text.lower()
        if retry_after is not None or name == "RetryAfter" or code == 429:
            return TelegramFailure("rate_limited", text or name, retry_after, code)
        if code is not None and code >= 500:
            return TelegramFailure("server", text or name, None, code)
        if name in {"TimedOut", "TimeoutError", "ReadTimeout", "ConnectTimeout"} or "timeout" in low:
            return TelegramFailure("timeout", text or name, None, code)
        if name in {"NetworkError", "OSError", "ConnectionError"} or "network" in low or "connection" in low:
            return TelegramFailure("network", text or name, None, code)
        if name == "Forbidden" or code == 403 or "forbidden" in low:
            return TelegramFailure("forbidden", text or name, None, code)
        if name == "BadRequest" or code == 400:
            return TelegramFailure("bad_request", text or name, None, code)
        return TelegramFailure("unknown", text or name, None, code)

    def note_rate_limit(self, scope_id: int | None, retry_after: int | None) -> None:
        if scope_id is None or retry_after is None:
            return
        delay = min(max(0, int(retry_after)), self.max_retry_after)
        self._cooldowns[int(scope_id)] = max(
            self._cooldowns.get(int(scope_id), 0.0), time.monotonic() + delay
        )

    def cooldown_remaining(self, scope_id: int | None) -> float:
        if scope_id is None:
            return 0.0
        until = self._cooldowns.get(int(scope_id), 0.0)
        remaining = max(0.0, until - time.monotonic())
        if remaining == 0.0:
            self._cooldowns.pop(int(scope_id), None)
        return remaining

    async def call_read(self, operation, *, scope_id: int | None = None):
        """Retry only safe/idempotent reads. Writes are intentionally excluded."""
        last = None
        for attempt in range(self.max_retries + 1):
            remaining = self.cooldown_remaining(scope_id)
            if remaining:
                await asyncio.sleep(min(remaining, self.max_retry_after))
            try:
                return await operation()
            except Exception as error:
                last = error
                failure = self.classify(error)
                from ghostea.services.observability import OBSERVABILITY
                OBSERVABILITY.emit("telegram_error", level="WARNING",
                                   kind=failure.kind, error_code=failure.error_code,
                                   retry_after=failure.retry_after, scope_id=scope_id)
                if failure.retry_after is not None:
                    self.note_rate_limit(scope_id, failure.retry_after)
                if not failure.transient or attempt >= self.max_retries:
                    raise
                delay = min(
                    float(failure.retry_after or (2 ** attempt)),
                    float(self.max_retry_after),
                )
                await asyncio.sleep(delay)
        raise last
