from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_vercel_session_probe_is_public_and_does_not_call_upstream():
    text = (ROOT / "dashboard" / "api" / "ghostea.js").read_text()
    marker = 'req.method === "GET" && req.query.action === "session"'
    assert marker in text
    start = text.index(marker)
    end = text.index('if (req.method === "POST" && req.query.action === "login")', start)
    block = text[start:end]
    assert "validSession(req)" in block
    assert "fetch(" not in block

def test_dashboard_bootstrap_uses_session_probe():
    text = (ROOT / "dashboard" / "index.html").read_text()
    assert "fetch('/api/ghostea?action=session')" in text
    assert "fetch('/api/ghostea?path=%2Fapi%2Fhealth')" not in text

def test_dashboard_login_requires_strong_session_secret():
    text = (ROOT / "dashboard" / "api" / "ghostea.js").read_text()
    assert "MIN_SECRET_LENGTH = 32" in text
    start = text.index('if (req.method === "POST" && req.query.action === "login")')
    block = text[start:text.index('const ip =', start)]
    assert 'secret("GHOSTEA_SESSION_SECRET").length < MIN_SECRET_LENGTH' in block
