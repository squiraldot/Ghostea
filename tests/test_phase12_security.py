from pathlib import Path

from ghostea.services.admin_service import _hash_password, _verify_password, AdminService

ROOT = Path(__file__).resolve().parents[1]


def test_password_hash_is_salted_scrypt_and_verifies():
    a = _hash_password("correct horse battery staple")
    b = _hash_password("correct horse battery staple")
    assert a.startswith("scrypt$16384$8$1$")
    assert a != b
    assert _verify_password("correct horse battery staple", a)
    assert not _verify_password("wrong password", a)


def test_admin_roles_fail_closed():
    assert not AdminService.allowed(None, "manage_admins")
    assert not AdminService.allowed("unknown", "read")
    assert AdminService.allowed("super_admin", "manage_admins")
    assert not AdminService.allowed("admin", "manage_admins")


def test_security_boundaries_present():
    web = (ROOT / "ghostea" / "web_server.py").read_text()
    proxy = (ROOT / "dashboard" / "api" / "ghostea.js").read_text()
    env = (ROOT / ".env.example").read_text()

    assert "GHOSTEA_PROXY_SIGNING_SECRET" in web
    assert "hmac.compare_digest" in web
    assert "X-Ghostea-Admin-Signature" in proxy
    assert "crypto.timingSafeEqual" in proxy
    assert "HttpOnly; Secure; SameSite=Lax" in proxy
    assert "Content-Security-Policy" in proxy
    assert "GHOSTEA_PROXY_SIGNING_SECRET" in env


def test_session_rejects_future_timestamp():
    proxy = (ROOT / "dashboard" / "api" / "ghostea.js").read_text()
    assert 'age < 0' in proxy
