from pathlib import Path
import os

ROOT = Path(__file__).resolve().parents[1]


def test_operations_snapshot_is_secret_free_and_reports_schema_and_alerts(monkeypatch):
    from ghostea.services.operations import build_operations_snapshot
    from ghostea.services.observability import Observability

    class DB:
        def health_check(self): return True
        def select(self, table, query):
            if table == "ghostea_schema_meta":
                return [{"schema_name": "ghostea", "schema_version": 11}]
            return []
        def check_tables(self, tables): return {name: True for name in tables}
        def count(self, table, query=None):
            status = (query or {}).get("status", "")
            return 2 if status == "eq.dead" else 0

    class Task:
        def done(self): return False
    class Queue:
        _task = Task()
        store = None

    obs = Observability()
    obs.emit("test_event", token="DO_NOT_LEAK", nested={"password": "DO_NOT_LEAK"})
    result = build_operations_snapshot(DB(), observability=obs, background_jobs=Queue(), readiness={"ready": True, "checks": []})

    assert result["database"]["schema_version"] == 11
    assert result["queue"]["dead"] == 2
    assert result["queue"]["worker_running"] is True
    assert any(alert["code"] == "dead_jobs" for alert in result["alerts"])
    rendered = str(result)
    assert "DO_NOT_LEAK" not in rendered


def test_operations_endpoint_and_ready_monitor_are_wired():
    web = (ROOT / "ghostea" / "web_server.py").read_text()
    proxy = (ROOT / "dashboard" / "api" / "ghostea.js").read_text()
    assert 'path == "/health/ready"' in web
    assert 'path == "/api/operations"' in web
    assert "build_operations_snapshot(" in web
    assert '"/api/operations"' in proxy


def test_schema_health_reports_actual_version_not_hardcoded_nine():
    web = (ROOT / "ghostea" / "web_server.py").read_text()
    assert '"version": 9 if table_status.get("ghostea_schema_meta") else None' not in web
    assert 'schema_version = None' in web
    assert '"version": schema_version' in web


def test_custom_vps_dashboard_is_supported():
    web = (ROOT / "ghostea" / "web_server.py").read_text()
    assert '== "custom"' in web
    assert 'GHOSTEA_DASHBOARD_HOST' in web


def test_supabase_count_and_health_probe_do_not_assume_id_column():
    db = (ROOT / "ghostea" / "storage" / "database.py").read_text()
    assert 'query.setdefault("select", "*")' in db
    assert 'self.select("ghostea_schema_meta", {"select": "schema_name", "limit": "0"})' in db
