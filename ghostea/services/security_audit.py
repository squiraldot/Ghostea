"""Phase 31 — deterministic security policy checks.

The audit is side-effect free and intentionally does not inspect or print
secret values. It validates configuration boundaries that protect the HTTP
proxy, authentication/session layer, webhook surface, and password verifier.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse


def validate_dashboard_target(value: str) -> tuple[bool, str]:
    """Require a clean HTTPS upstream target with no embedded credentials."""
    raw = str(value or "").strip()
    if not raw:
        return False, "missing"
    try:
        parsed = urlparse(raw)
    except ValueError:
        return False, "invalid_url"
    if parsed.scheme != "https" or not parsed.hostname:
        return False, "https_required"
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        return False, "credentials_query_fragment_forbidden"
    if parsed.path not in ("", "/"):
        return False, "path_forbidden"
    if not re.fullmatch(r"[A-Za-z0-9.-]{1,253}", parsed.hostname):
        return False, "invalid_hostname"
    return True, "valid"


def run_security_audit() -> dict:
    import os
    from ghostea.services.production_readiness import local_readiness
    checks = []
    target_ok, target_detail = validate_dashboard_target(os.getenv("GHOSTEA_API_URL", ""))
    checks.append({"name": "dashboard_upstream_policy", "ok": target_ok, "detail": target_detail})
    checks.append({"name": "proxy_secret_length", "ok": len(os.getenv("GHOSTEA_PROXY_SIGNING_SECRET", "").strip()) >= 32, "detail": "strong_length"})
    checks.append({"name": "dashboard_api_key_length", "ok": len(os.getenv("DASHBOARD_API_KEY", "").strip()) >= 32, "detail": "strong_length"})
    readiness = local_readiness()
    checks.append({"name": "production_readiness", "ok": bool(all(c.ok for c in readiness)), "detail": "all_checks_pass" if all(c.ok for c in readiness) else "readiness_failed"})
    return {"ready": all(c["ok"] for c in checks), "checks": checks}
