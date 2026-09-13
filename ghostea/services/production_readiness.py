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
from urllib.parse import urlparse

from ghostea.services.chat_capabilities import resolve_chat_capabilities
from ghostea.services.chat_visibility import resolve_chat_visibility
from ghostea.services.chat_context import ChatContext
from ghostea.services.telegram_contract import TELEGRAM_CONTRACT
from ghostea.services.compatibility_matrix import build_matrix, validate_matrix, matrix_summary
from ghostea.services.adversarial_regression import run_adversarial_regression
from ghostea.services.input_boundary import run_input_boundary_regression
from ghostea.services.deployment_profile import load_deployment_profile


BASE_REQUIRED_ENV = ("BOT_TOKEN", "DASHBOARD_API_KEY", "DASHBOARD_ORIGIN", "GHOSTEA_PROXY_SIGNING_SECRET")
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
    profile = load_deployment_profile()
    profile_errors = profile.validate()
    checks.append(ReadinessCheck("deployment_profile", not profile_errors, "valid" if not profile_errors else "; ".join(profile_errors)))
    provider_env = {
        "supabase_rest": ("SUPABASE_URL", "SUPABASE_KEY"),
        "postgresql": ("DATABASE_URL",),
    }.get(profile.database_provider, ())
    storage_env = {
        "supabase": ("SUPABASE_URL", "SUPABASE_KEY"),
        "local": (),
        "s3": ("GHOSTEA_S3_BUCKET", "GHOSTEA_S3_ACCESS_KEY", "GHOSTEA_S3_SECRET_KEY"),
    }.get(profile.storage_provider, ())
    dashboard_env = ("GHOSTEA_SESSION_SECRET",) if profile.dashboard_host == "vps" else ()
    for name in BASE_REQUIRED_ENV + provider_env + storage_env + dashboard_env:
        present = bool(os.getenv(name, "").strip())
        checks.append(ReadinessCheck(name, present, "configured" if present else "missing"))
    if profile.storage_provider == "supabase":
        bucket = os.getenv("GHOSTEA_SUPABASE_STORAGE_BUCKET", "ghostea").strip()
        bucket_ok = bool(bucket) and __import__("re").fullmatch(r"[A-Za-z0-9._-]{1,100}", bucket) is not None
        checks.append(ReadinessCheck(
            "supabase_storage_bucket_policy",
            bucket_ok,
            "valid_bucket" if bucket_ok else "GHOSTEA_SUPABASE_STORAGE_BUCKET is invalid",
        ))
    for rel in REQUIRED_FILES:
        exists = (root / rel).is_file()
        checks.append(ReadinessCheck(str(rel), exists, "present" if exists else "missing"))
    # Configuration policy: do not report secret values, only safe metadata.
    origin = os.getenv("DASHBOARD_ORIGIN", "").strip()
    supabase_url = os.getenv("SUPABASE_URL", "").strip()
    database_url = os.getenv("DATABASE_URL", "").strip()
    api_key = os.getenv("DASHBOARD_API_KEY", "").strip()
    proxy_secret = os.getenv("GHOSTEA_PROXY_SIGNING_SECRET", "").strip()

    def _https_or_local(value):
        parsed = urlparse(value)
        if parsed.scheme == "https" and bool(parsed.netloc):
            return True
        if parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}:
            return True
        return False

    checks.append(
        ReadinessCheck(
            "dashboard_origin_policy",
            _https_or_local(origin),
            "valid_origin" if _https_or_local(origin) else "DASHBOARD_ORIGIN must be https (localhost is allowed for development)",
        )
    )
    if profile.database_provider == "supabase_rest":
        checks.append(
            ReadinessCheck(
                "supabase_url_policy",
                _https_or_local(supabase_url),
                "valid_url" if _https_or_local(supabase_url) else "SUPABASE_URL must use https (localhost is allowed for development)",
            )
        )
    elif profile.database_provider == "postgresql":
        parsed_db = urlparse(database_url)
        valid_db = parsed_db.scheme in {"postgresql", "postgres"} and bool(parsed_db.hostname)
        checks.append(
            ReadinessCheck(
                "database_url_policy",
                valid_db,
                "valid_postgresql_url" if valid_db else "DATABASE_URL must be a valid PostgreSQL connection URL",
            )
        )
    checks.append(
        ReadinessCheck(
            "dashboard_api_key_entropy",
            len(api_key) >= 32,
            "strong_length" if len(api_key) >= 32 else "DASHBOARD_API_KEY must be at least 32 characters",
        )
    )
    update_mode = os.getenv("GHOSTEA_UPDATE_MODE", "polling").strip().lower()
    checks.append(
        ReadinessCheck(
            "telegram_update_mode",
            update_mode in {"polling", "webhook"},
            "polling_or_webhook" if update_mode in {"polling", "webhook"} else "GHOSTEA_UPDATE_MODE must be polling or webhook",
        )
    )
    if update_mode == "webhook":
        webhook_url = os.getenv("GHOSTEA_WEBHOOK_URL", "").strip()
        webhook_secret = os.getenv("GHOSTEA_WEBHOOK_SECRET_TOKEN", "").strip()
        webhook_path = os.getenv("GHOSTEA_WEBHOOK_PATH", "/telegram/webhook").strip() or "/telegram/webhook"
        parsed_webhook = urlparse(webhook_url)
        webhook_url_ok = parsed_webhook.scheme == "https" and bool(parsed_webhook.netloc) and not parsed_webhook.query and not parsed_webhook.fragment
        path_ok = webhook_path.startswith("/") and len(webhook_path) <= 200 and "?" not in webhook_path and "#" not in webhook_path
        checks.append(ReadinessCheck("webhook_url_policy", webhook_url_ok, "valid_https_url" if webhook_url_ok else "GHOSTEA_WEBHOOK_URL must be a clean https URL"))
        checks.append(ReadinessCheck("webhook_path_policy", path_ok and parsed_webhook.path.rstrip("/") == webhook_path.rstrip("/"), "valid_path" if path_ok and parsed_webhook.path.rstrip("/") == webhook_path.rstrip("/") else "webhook URL path must match GHOSTEA_WEBHOOK_PATH"))
        secret_ok = 1 <= len(webhook_secret) <= 256
        checks.append(ReadinessCheck("webhook_secret_policy", secret_ok, "valid_length" if secret_ok else "GHOSTEA_WEBHOOK_SECRET_TOKEN must be 1-256 characters"))
    checks.append(
        ReadinessCheck(
            "proxy_signing_secret_entropy",
            len(proxy_secret) >= 32,
            "strong_length" if len(proxy_secret) >= 32 else "GHOSTEA_PROXY_SIGNING_SECRET must be at least 32 characters",
        )
    )
    if profile.dashboard_host == "vps":
        session_secret = os.getenv("GHOSTEA_SESSION_SECRET", "").strip()
        checks.append(
            ReadinessCheck(
                "dashboard_session_secret_entropy",
                len(session_secret) >= 32,
                "strong_length" if len(session_secret) >= 32 else "GHOSTEA_SESSION_SECRET must be at least 32 characters",
            )
        )
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
