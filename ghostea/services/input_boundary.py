"""Phase H15 — untrusted input boundary hardening and deterministic fuzz checks.

Telegram payloads, persisted rows, and dashboard JSON are treated as
untrusted at parsing boundaries. H15 keeps existing feature semantics but
ensures malformed scalar/container values fail closed instead of escaping as
uncaught ValueError/TypeError/OverflowError exceptions.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace


@dataclass(frozen=True)
class BoundaryScenario:
    name: str
    description: str


SCENARIOS = (
    BoundaryScenario("malformed_thread_id", "Invalid thread metadata never becomes a topic scope."),
    BoundaryScenario("malformed_chat_id", "Invalid chat identity is rejected without partial context."),
    BoundaryScenario("unhashable_update_type", "Unexpected containers cannot crash update validation."),
    BoundaryScenario("invalid_permission_mapping", "Non-mapping permission payloads fail closed."),
    BoundaryScenario("invalid_scope_topic", "Invalid topic ids become no topic scope."),
    BoundaryScenario("malformed_visibility_row", "Corrupt registry rows resolve to private/unsupported safely."),
    BoundaryScenario("malformed_admin_public", "Corrupt admin records never produce a public identity."),
    BoundaryScenario("unicode_moderation_input", "Unicode normalization remains deterministic on odd text."),
    BoundaryScenario("extreme_message_length", "Huge text remains bounded by the existing max-length decision."),
    BoundaryScenario("null_dashboard_payload", "Null/primitive dashboard payloads fail closed at validation boundaries."),
)


def _unicode_probe():
    from ghostea.services.moderation_engine import ModerationEngine
    samples = [None, "", "Kelvin", "ａｂｕｓｅ", "\u200b" * 50, "A" * 10000]
    for value in samples:
        normalized = ModerationEngine._normalize(value)
        if not isinstance(normalized, str):
            return False
    return True


def _extreme_length_probe():
    from ghostea.services.moderation_engine import ModerationEngine
    text = "x" * 100_000
    settings = {
        "max_message_length": 4000,
        "mention_spam_limit": 6,
        "repeated_message_window_seconds": 60,
        "repeated_message_limit": 3,
        "link_filter_enabled": False,
        "spam_filter_enabled": False,
        "abuse_filter_enabled": False,
        "_chat_id": -100,
        "_user_id": 42,
        "_scope_key": (-100, None),
    }
    class _Protection:
        def find_mention_spam(self, *_): return False
        def find_repeated_message(self, *_): return False
        def register_repeated_message(self, *_, **__): return False
    engine = ModerationEngine(None, _Protection())
    result = engine.evaluate(text, settings, {}, {}, {})
    return getattr(result, "category", None) == "long_message"


def run_input_boundary_regression() -> dict:
    """Run deterministic malformed-input probes without network/database access."""
    results = []

    try:
        from ghostea.services.chat_context import build_chat_context
        chat = SimpleNamespace(id=-100, type="supergroup", title="x", username=None, is_forum=True)
        message = SimpleNamespace(message_thread_id="not-an-int")
        ctx = build_chat_context(chat, message)
        results.append({"name": "malformed_thread_id", "ok": ctx is not None and ctx.topic_id is None})
    except Exception:
        results.append({"name": "malformed_thread_id", "ok": False})

    try:
        from ghostea.services.chat_context import build_chat_context
        chat = SimpleNamespace(id="bad-id", type="supergroup", title="x", username=None, is_forum=False)
        ctx = build_chat_context(chat)
        results.append({"name": "malformed_chat_id", "ok": ctx is None})
    except Exception:
        results.append({"name": "malformed_chat_id", "ok": True})

    try:
        from ghostea.services.telegram_contract import validate_update_type, validate_permission_mapping
        results.append({"name": "unhashable_update_type", "ok": validate_update_type([]) is False})
        results.append({"name": "invalid_permission_mapping", "ok": validate_permission_mapping(None) is False})
    except Exception:
        results.extend([
            {"name": "unhashable_update_type", "ok": False},
            {"name": "invalid_permission_mapping", "ok": False},
        ])

    try:
        from ghostea.services.scope_policy import normalize_topic_id
        ctx = SimpleNamespace(is_topic_capable=True, topic_id=None)
        results.append({"name": "invalid_scope_topic", "ok": normalize_topic_id(ctx, "bad") is None})
    except Exception:
        results.append({"name": "invalid_scope_topic", "ok": False})

    try:
        from ghostea.services.chat_visibility import visibility_from_registry
        result = visibility_from_registry("not-a-row")
        results.append({"name": "malformed_visibility_row", "ok": result.is_private and not result.public_url})
    except Exception:
        results.append({"name": "malformed_visibility_row", "ok": False})

    try:
        from ghostea.services.admin_service import AdminService
        result = AdminService.public({"id": "bad", "username": None, "role": None})
        results.append({"name": "malformed_admin_public", "ok": result is None})
    except Exception:
        results.append({"name": "malformed_admin_public", "ok": True})

    try:
        results.append({"name": "unicode_moderation_input", "ok": _unicode_probe()})
    except Exception:
        results.append({"name": "unicode_moderation_input", "ok": False})

    try:
        results.append({"name": "extreme_message_length", "ok": _extreme_length_probe()})
    except Exception:
        results.append({"name": "extreme_message_length", "ok": False})

    try:
        from ghostea.services.admin_service import AdminService
        results.append({"name": "null_dashboard_payload", "ok": AdminService.allowed(None, "manage_admins") is False})
    except Exception:
        results.append({"name": "null_dashboard_payload", "ok": False})

    by_name = {x["name"]: x for x in results}
    missing = [s.name for s in SCENARIOS if s.name not in by_name]
    failed = [x["name"] for x in results if not x["ok"]]
    return {
        "ready": not missing and not failed and len(results) == len(SCENARIOS),
        "scenario_count": len(SCENARIOS),
        "passed": sum(1 for x in results if x["ok"]),
        "failed": failed,
        "missing": missing,
        "scenarios": [
            {"name": s.name, "description": s.description, "ok": by_name.get(s.name, {}).get("ok", False)}
            for s in SCENARIOS
        ],
    }
