from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_resource_monitor_route_exists():
    s = (ROOT / "ghostea/web_server.py").read_text(encoding="utf-8")
    assert 'path.startswith("/api/groups/") and path.endswith("/resources")' in s
    assert '"ghostea_resources"' in s
    assert '"counts"' in s
    assert '"files"' in s and '"urls"' in s and '"flags"' in s


def test_vercel_proxy_allows_resource_monitoring():
    s = (ROOT / "dashboard/api/ghostea.js").read_text(encoding="utf-8")
    assert 'const resources = pathname.match(/^\\/api\\/groups\\/(-?\\d+)\\/resources$/);' in s
    assert 'Boolean(resources)' in s


def test_dashboard_has_resource_monitor():
    s = (ROOT / "dashboard/index.html").read_text(encoding="utf-8")
    for token in (
        'data-section="resources"',
        'id="resources"',
        'id="resourceRows"',
        'id="resTotal"',
        'id="resFiles"',
        'id="resUrls"',
        'id="resFlags"',
        "loadResources",
        "/resources?limit=100",
    ):
        assert token in s
