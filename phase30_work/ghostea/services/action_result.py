"""Phase H03 — explicit Telegram action outcomes.

Detection/state transitions and Telegram side effects are deliberately kept
separate.  Callers can distinguish a successful punishment from a failed or
unsupported Telegram operation without guessing from exceptions.
"""
from dataclasses import dataclass
import time
from enum import Enum


class ActionStatus(str, Enum):
    SUCCESS = "success"
    SKIPPED_UNSUPPORTED = "skipped_unsupported"
    SKIPPED_NO_PERMISSION = "skipped_no_permission"
    FAILED_TELEGRAM = "failed_telegram"
    FAILED_TRANSIENT = "failed_transient"
    FAILED_UNKNOWN = "failed_unknown"


@dataclass(frozen=True)
class ActionResult:
    action: str
    status: ActionStatus
    detail: str = ""
    retry_after: int | None = None

    @property
    def ok(self) -> bool:
        return self.status is ActionStatus.SUCCESS


def classify_exception(error: Exception) -> tuple[ActionStatus, str, int | None]:
    """Classify Telegram/PTB failures using the H05 central policy."""
    from ghostea.services.telegram_resilience import TelegramErrorPolicy
    failure = TelegramErrorPolicy.classify(error)
    if failure.kind == "rate_limited":
        return ActionStatus.FAILED_TRANSIENT, f"rate_limited:{failure.detail}", failure.retry_after
    if failure.kind in {"network", "timeout", "server"}:
        return ActionStatus.FAILED_TRANSIENT, failure.detail, failure.retry_after
    if failure.kind == "forbidden":
        return ActionStatus.SKIPPED_NO_PERMISSION, failure.detail, None
    if failure.kind == "bad_request":
        return ActionStatus.FAILED_TELEGRAM, failure.detail, None
    text = failure.detail.lower()
    if "not supported" in text or "unsupported" in text:
        return ActionStatus.SKIPPED_UNSUPPORTED, failure.detail, None
    if "permission" in text or "not an administrator" in text:
        return ActionStatus.SKIPPED_NO_PERMISSION, failure.detail, None
    return ActionStatus.FAILED_UNKNOWN, failure.detail, failure.retry_after


_CONCURRENCY_GATE = None

def set_concurrency_gate(gate):
    global _CONCURRENCY_GATE
    _CONCURRENCY_GATE = gate


async def execute_action(action: str, operation):
    from ghostea.services.observability import OBSERVABILITY
    started = time.monotonic()
    try:
        if _CONCURRENCY_GATE is None:
            await operation()
        else:
            async with _CONCURRENCY_GATE.external():
                await operation()
    except Exception as error:
        status, detail, retry_after = classify_exception(error)
        result = ActionResult(action, status, detail, retry_after)
        OBSERVABILITY.observe_duration(
            "telegram_action",
            time.monotonic() - started,
        )
        OBSERVABILITY.emit("telegram_action", level="WARNING",
                           action=action, status=result.status.value,
                           detail=detail, retry_after=retry_after)
        return result
    result = ActionResult(action, ActionStatus.SUCCESS)
    OBSERVABILITY.observe_duration(
        "telegram_action",
        time.monotonic() - started,
    )
    OBSERVABILITY.emit("telegram_action", action=action, status=result.status.value)
    return result
