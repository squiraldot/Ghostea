"""Deployment profile setup and validation helpers.

The module is side-effect free: it never writes secrets or prints secret values.
"""
from dataclasses import dataclass
from typing import Mapping

from ghostea.services.deployment_profile import (
    DeploymentProfile,
    SUPPORTED_DATABASE_PROVIDERS,
    SUPPORTED_STORAGE_PROVIDERS,
    SUPPORTED_DASHBOARD_HOSTS,
    load_deployment_profile,
)


import re
from urllib.parse import urlparse

_POSTGRES_SCHEMES = {"postgres", "postgresql"}
_HTTP_SCHEMES = {"http", "https"}
_S3_BUCKET_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")


def _validate_provider_environment(source: Mapping[str, str], profile: DeploymentProfile) -> list[str]:
    """Validate provider-specific configuration without making network calls."""
    errors: list[str] = []

    def value(name: str) -> str:
        return str(source.get(name, "") or "").strip()

    if profile.database_provider == "supabase_rest":
        parsed = urlparse(value("SUPABASE_URL"))
        if parsed.scheme not in _HTTP_SCHEMES or not parsed.netloc:
            errors.append("SUPABASE_URL must be an absolute http(s) URL")
    elif profile.database_provider == "postgresql":
        parsed = urlparse(value("DATABASE_URL"))
        if parsed.scheme not in _POSTGRES_SCHEMES or not parsed.netloc:
            errors.append("DATABASE_URL must be a valid postgres:// or postgresql:// URL")

    if profile.storage_provider == "supabase":
        parsed = urlparse(value("SUPABASE_URL"))
        if parsed.scheme not in _HTTP_SCHEMES or not parsed.netloc:
            errors.append("SUPABASE_URL must be an absolute http(s) URL")
        bucket = value("GHOSTEA_SUPABASE_STORAGE_BUCKET") or "ghostea"
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", bucket):
            errors.append("GHOSTEA_SUPABASE_STORAGE_BUCKET contains invalid characters")
    elif profile.storage_provider == "s3":
        bucket = value("GHOSTEA_S3_BUCKET")
        if not _S3_BUCKET_RE.fullmatch(bucket):
            errors.append("GHOSTEA_S3_BUCKET must be a valid S3-style bucket name")
        endpoint = value("GHOSTEA_S3_ENDPOINT_URL")
        if endpoint:
            parsed = urlparse(endpoint)
            if parsed.scheme not in _HTTP_SCHEMES or not parsed.netloc:
                errors.append("GHOSTEA_S3_ENDPOINT_URL must be an absolute http(s) URL")
        if value("GHOSTEA_S3_REGION") and len(value("GHOSTEA_S3_REGION")) > 63:
            errors.append("GHOSTEA_S3_REGION is too long")

    update_mode = value("GHOSTEA_UPDATE_MODE") or "polling"
    if update_mode not in {"polling", "webhook"}:
        errors.append("GHOSTEA_UPDATE_MODE must be 'polling' or 'webhook'")
    if update_mode == "webhook":
        webhook_url = value("GHOSTEA_WEBHOOK_URL")
        webhook_secret = value("GHOSTEA_WEBHOOK_SECRET_TOKEN")
        webhook_path = value("GHOSTEA_WEBHOOK_PATH") or "/telegram/webhook"
        parsed = urlparse(webhook_url)
        if parsed.scheme != "https" or not parsed.netloc:
            errors.append("GHOSTEA_WEBHOOK_URL must be an absolute https URL")
        if parsed.query or parsed.fragment:
            errors.append("GHOSTEA_WEBHOOK_URL must not contain a query string or fragment")
        if not webhook_path.startswith("/") or len(webhook_path) > 200 or "?" in webhook_path or "#" in webhook_path:
            errors.append("GHOSTEA_WEBHOOK_PATH must be a clean absolute path")
        elif parsed.path.rstrip("/") != webhook_path.rstrip("/"):
            errors.append("GHOSTEA_WEBHOOK_URL path must match GHOSTEA_WEBHOOK_PATH")
        if not 1 <= len(webhook_secret) <= 256:
            errors.append("GHOSTEA_WEBHOOK_SECRET_TOKEN must be 1-256 characters")
    if profile.dashboard_host == "vps":
        origin = value("DASHBOARD_ORIGIN")
        parsed = urlparse(origin)
        # A VPS dashboard may be same-origin behind nginx, but a configured
        # absolute origin must still be syntactically valid.
        if origin and (parsed.scheme not in _HTTP_SCHEMES or not parsed.netloc):
            errors.append("DASHBOARD_ORIGIN must be an absolute http(s) URL when configured")
    return errors

PROFILE_TEMPLATES = {
    "managed": {
        "GHOSTEA_DEPLOYMENT_MODE": "managed",
        "GHOSTEA_DATABASE_PROVIDER": "supabase_rest",
        "GHOSTEA_STORAGE_PROVIDER": "supabase",
        "GHOSTEA_DASHBOARD_HOST": "vercel",
        "GHOSTEA_UPDATE_MODE": "polling",
    },
    "self_hosted": {
        "GHOSTEA_DEPLOYMENT_MODE": "self_hosted",
        "GHOSTEA_DATABASE_PROVIDER": "postgresql",
        "GHOSTEA_STORAGE_PROVIDER": "local",
        "GHOSTEA_DASHBOARD_HOST": "vps",
        "GHOSTEA_UPDATE_MODE": "polling",
    },
    "custom": {
        "GHOSTEA_DEPLOYMENT_MODE": "custom",
        "GHOSTEA_DATABASE_PROVIDER": "supabase_rest",
        "GHOSTEA_STORAGE_PROVIDER": "supabase",
        "GHOSTEA_DASHBOARD_HOST": "vercel",
        "GHOSTEA_UPDATE_MODE": "polling",
    },
}


@dataclass(frozen=True)
class SetupResult:
    profile: DeploymentProfile
    errors: tuple[str, ...]
    required_env: tuple[str, ...]
    template: dict[str, str]

    @property
    def ready(self):
        return not self.errors


def required_environment(profile: DeploymentProfile) -> tuple[str, ...]:
    required = ["BOT_TOKEN", "DASHBOARD_API_KEY", "DASHBOARD_ORIGIN", "GHOSTEA_PROXY_SIGNING_SECRET"]
    if profile.database_provider == "supabase_rest":
        required += ["SUPABASE_URL", "SUPABASE_KEY"]
    elif profile.database_provider == "postgresql":
        required += ["DATABASE_URL"]
    if profile.storage_provider == "supabase":
        required += ["SUPABASE_URL", "SUPABASE_KEY"]
    elif profile.storage_provider == "s3":
        required += ["GHOSTEA_S3_BUCKET", "GHOSTEA_S3_ACCESS_KEY", "GHOSTEA_S3_SECRET_KEY"]
    if profile.dashboard_host == "vps":
        required += ["GHOSTEA_SESSION_SECRET"]
    return tuple(dict.fromkeys(required))


def profile_template(mode: str, *, database=None, storage=None, dashboard=None) -> dict[str, str]:
    mode = str(mode).strip().lower()
    if mode not in PROFILE_TEMPLATES:
        raise ValueError(f"Unsupported setup profile: {mode}")
    values = dict(PROFILE_TEMPLATES[mode])
    if mode == "custom":
        if database is not None:
            values["GHOSTEA_DATABASE_PROVIDER"] = str(database).strip().lower()
        if storage is not None:
            values["GHOSTEA_STORAGE_PROVIDER"] = str(storage).strip().lower()
        if dashboard is not None:
            values["GHOSTEA_DASHBOARD_HOST"] = str(dashboard).strip().lower()
    return values


def build_setup_result(env: Mapping[str, str], mode: str | None = None, *, database=None, storage=None, dashboard=None) -> SetupResult:
    source = dict(env)
    requested_mode = str(mode).strip().lower() if mode is not None else None
    if requested_mode in {"managed", "self_hosted"}:
        template = profile_template(requested_mode)
        # Deployment profile keys are canonical; operational knobs such as
        # GHOSTEA_UPDATE_MODE remain caller-controlled.
        for key, value in template.items():
            if key != "GHOSTEA_UPDATE_MODE":
                source[key] = value
        source["GHOSTEA_DEPLOYMENT_MODE"] = requested_mode
    elif requested_mode == "custom":
        source["GHOSTEA_DEPLOYMENT_MODE"] = "custom"
        # Unlike the canonical profiles, custom mode must not silently choose
        # a provider tuple. CLI flags or explicit environment values define it.
        if database is not None:
            source["GHOSTEA_DATABASE_PROVIDER"] = str(database).strip().lower()
        if storage is not None:
            source["GHOSTEA_STORAGE_PROVIDER"] = str(storage).strip().lower()
        if dashboard is not None:
            source["GHOSTEA_DASHBOARD_HOST"] = str(dashboard).strip().lower()
    elif requested_mode is not None:
        source["GHOSTEA_DEPLOYMENT_MODE"] = requested_mode

    profile = load_deployment_profile(source)
    errors = list(profile.validate())
    errors.extend(_validate_provider_environment(source, profile))
    if requested_mode == "custom":
        for key in ("GHOSTEA_DATABASE_PROVIDER", "GHOSTEA_STORAGE_PROVIDER", "GHOSTEA_DASHBOARD_HOST"):
            if not str(source.get(key, "") or "").strip():
                errors.append(f"Custom profile requires {key}")

    required = list(required_environment(profile))
    update_mode = str(source.get("GHOSTEA_UPDATE_MODE", "polling") or "polling").strip().lower()
    if update_mode == "webhook":
        required += ["GHOSTEA_WEBHOOK_URL", "GHOSTEA_WEBHOOK_SECRET_TOKEN"]
    required = tuple(dict.fromkeys(required))
    for name in required:
        if not str(source.get(name, "") or "").strip():
            errors.append(f"Missing required environment variable: {name}")
    for name in ("DASHBOARD_API_KEY", "GHOSTEA_PROXY_SIGNING_SECRET"):
        value = str(source.get(name, "") or "").strip()
        if value and len(value) < 32:
            errors.append(f"{name} must be at least 32 characters")
    if profile.dashboard_host == "vps":
        value = str(source.get("GHOSTEA_SESSION_SECRET", "") or "").strip()
        if value and len(value) < 32:
            errors.append("GHOSTEA_SESSION_SECRET must be at least 32 characters")
    template = profile_template(profile.mode,
                                database=profile.database_provider,
                                storage=profile.storage_provider,
                                dashboard=profile.dashboard_host) if profile.mode in PROFILE_TEMPLATES else {}
    return SetupResult(profile, tuple(dict.fromkeys(errors)), required, template)


def render_env_template(mode: str, *, database=None, storage=None, dashboard=None) -> str:
    values = profile_template(mode, database=database, storage=storage, dashboard=dashboard)
    lines = ["# Generated by Ghostea Phase 24 setup helper.", "# Fill secret/provider values; do not commit this file.", ""]
    for key, value in values.items():
        lines.append(f"{key}={value}")
    lines += ["", "BOT_TOKEN=", "DASHBOARD_API_KEY=", "DASHBOARD_ORIGIN=", "GHOSTEA_PROXY_SIGNING_SECRET="]
    if values["GHOSTEA_DATABASE_PROVIDER"] == "supabase_rest" or values["GHOSTEA_STORAGE_PROVIDER"] == "supabase":
        lines += ["SUPABASE_URL=", "SUPABASE_KEY="]
    if values["GHOSTEA_STORAGE_PROVIDER"] == "supabase":
        lines += ["GHOSTEA_SUPABASE_STORAGE_BUCKET=ghostea"]
    if values["GHOSTEA_DATABASE_PROVIDER"] == "postgresql":
        lines += ["DATABASE_URL="]
    if values["GHOSTEA_STORAGE_PROVIDER"] == "local":
        lines += ["GHOSTEA_LOCAL_STORAGE_ROOT=/app/data/storage"]
    if values["GHOSTEA_STORAGE_PROVIDER"] == "s3":
        lines += ["GHOSTEA_S3_BUCKET=", "GHOSTEA_S3_ACCESS_KEY=", "GHOSTEA_S3_SECRET_KEY=", "GHOSTEA_S3_REGION=us-east-1", "GHOSTEA_S3_ENDPOINT_URL="]
    if values["GHOSTEA_DASHBOARD_HOST"] == "vps":
        lines += ["GHOSTEA_SESSION_SECRET="]
    if values.get("GHOSTEA_UPDATE_MODE") == "webhook":
        lines += ["GHOSTEA_WEBHOOK_URL=", "GHOSTEA_WEBHOOK_SECRET_TOKEN=", "GHOSTEA_WEBHOOK_PATH=/telegram/webhook"]
    return "\n".join(lines) + "\n"
