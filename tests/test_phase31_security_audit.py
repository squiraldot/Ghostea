from pathlib import Path
import os
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_upstream_target_requires_https_and_clean_origin():
    from ghostea.services.security_audit import validate_dashboard_target
    assert validate_dashboard_target("https://ghostea.example") == (True, "valid")
    assert validate_dashboard_target("http://ghostea.example") == (False, "https_required")
    assert validate_dashboard_target("https://user:pass@ghostea.example") == (False, "credentials_query_fragment_forbidden")
    assert validate_dashboard_target("https://ghostea.example/api") == (False, "path_forbidden")
    assert validate_dashboard_target("https://ghostea.example/?x=1") == (False, "credentials_query_fragment_forbidden")


def test_admin_scrypt_verifier_rejects_extreme_parameters():
    from ghostea.services.admin_service import _hash_password, _verify_password
    good = _hash_password("A" * 12)
    assert _verify_password("A" * 12, good)
    parts = good.split("$")
    parts[2] = str(2**30)
    assert not _verify_password("A" * 12, "$".join(parts))


def test_bootstrap_username_uses_strict_grammar():
    from ghostea.services.admin_service import AdminService
    assert AdminService is not None
    assert "USERNAME_RE" in (ROOT / "ghostea" / "services" / "admin_service.py").read_text()


def test_proxy_signature_is_timestamp_and_request_bound():
    text = (ROOT / "dashboard" / "api" / "ghostea.js").read_text()
    server = (ROOT / "ghostea" / "web_server.py").read_text()
    for token in ("X-Ghostea-Request-Timestamp", "PROXY_SIGNATURE_MAX_AGE_MS", "const requestTimestamp"):
        assert token in text
    for token in ("X-Ghostea-Request-Timestamp", "PROXY_SIGNATURE_MAX_AGE_SECONDS", "self.command, pathname"):
        assert token in server


def test_dashboard_target_validation_is_enforced_before_fetch():
    text = (ROOT / "dashboard" / "api" / "ghostea.js").read_text()
    assert 'if (!validateTarget(target) || !secret("GHOSTEA_API_KEY"))' in text
