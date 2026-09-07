"""Phase 20 — final compatibility and production readiness checks.

The readiness layer is intentionally side-effect free. It validates local
configuration/runtime prerequisites and exposes one canonical compatibility
matrix for diagnostics. Telegram permissions remain dynamic and are checked
only when a live chat is inspected.
"""
from dataclasses import dataclass
from pathlib import Path
import os
import sys

from ghostea.services.chat_capabilities import resolve_chat_capabilities
from ghostea.services.chat_visibility import resolve_chat_visibility
from ghostea.services.chat_context import ChatContext
from ghostea.services.telegram_contract import TELEGRAM_CONTRACT
from ghostea.services.compatibility_matrix import build_matrix, validate_matrix, matrix_summary
from ghostea.services.adversarial_regression import run_adversarial_regression
from ghostea.services.input_boundary import run_input_boundary_regression


REQUIRED_ENV = ("BOT_TOKEN", "SUPABASE_URL", "SUPABASE_KEY", "DASHBOARD_API_KEY", "DASHBOARD_ORIGIN")
REQUIRED_FILES = (
    Path("ghostea/filters/abusive_words.txt"),
    Path("ghostea/filters/spam_patterns.txt"),
    Path("ghostea/filters/blocked_domains.txt"),
)


@dataclass(frozen=True)
class ReadinessCheck:
    name: str
    ok: bool
    detail: str

    def as_dict(self):
        return {"name": self.name, "ok": self.ok, "detail": self.detail}


def local_readiness(base_dir=None):
    """Return deterministic local production checks without network calls."""
    root = Path(base_dir or Path(__file__).resolve().parents[2])
    checks = []
    for name in REQUIRED_ENV:
        present = bool(os.getenv(name, "").strip())
        checks.append(ReadinessCheck(name, present, "configured" if present else "missing"))
    for rel in REQUIRED_FILES:
        exists = (root / rel).is_file()
        checks.append(ReadinessCheck(str(rel), exists, "present" if exists else "missing"))
    checks.append(ReadinessCheck("python", sys.version_info >= (3, 9), sys.version.split()[0]))
    checks.append(
        ReadinessCheck(
            "telegram_api_contract",
            bool(TELEGRAM_CONTRACT.bot_api_baseline and TELEGRAM_CONTRACT.ptb_major == 22),
            f"Bot API {TELEGRAM_CONTRACT.bot_api_baseline}; python-telegram-bot major {TELEGRAM_CONTRACT.ptb_major}",
        )
    )
    matrix_errors = validate_matrix(build_matrix())
    checks.append(
        ReadinessCheck(
            "telegram_compatibility_matrix",
            not matrix_errors,
            "valid" if not matrix_errors else "; ".join(matrix_errors),
        )
    )
    adversarial = run_adversarial_regression()
    checks.append(
        ReadinessCheck(
            "adversarial_regression",
            bool(adversarial.get("ready")),
            f"{adversarial.get('passed', 0)}/{adversarial.get('scenario_count', 0)} scenarios passed",
        )
    )
    boundaries = run_input_boundary_regression()
    checks.append(
        ReadinessCheck(
            "input_boundary_regression",
            bool(boundaries.get("ready")),
            f"{boundaries.get('passed', 0)}/{boundaries.get('scenario_count', 0)} scenarios passed",
        )
    )
    return checks


def readiness_summary(checks):
    checks = list(checks)
    return {
        "ready": all(c.ok for c in checks),
        "checks": [c.as_dict() for c in checks],
    }


def compatibility_matrix():
    """Return the canonical H13 Telegram compatibility matrix."""
    return build_matrix()


def compatibility_readiness():
    """Validate the deterministic H13 matrix without network calls."""
    matrix = build_matrix()
    errors = validate_matrix(matrix)
    return {
        "ready": not errors,
        "case_count": len(matrix),
        "validation_errors": errors,
    }


def compatibility_summary():
    """Expose the full matrix contract for diagnostics."""
    return matrix_summary()
