from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def test_phase9_schema_marker_and_integrity_constraints():
    sql = (ROOT / "database.sql").read_text(encoding="utf-8")
    assert "ghostea_schema_meta" in sql
    assert "values ('ghostea', 9)" in sql
    assert "idx_ghostea_resources_chat_created" in sql
    assert "idx_ghostea_upload_sessions_user_updated" in sql
    assert ("ux_ghostea_upload_sessions_one_active_per_user" in sql or "idx_ghostea_upload_sessions_user_nonterminal" in sql)


def test_schema_state_matches_upload_workflow_enum():
    sql = (ROOT / "database.sql").read_text(encoding="utf-8")
    workflow = (ROOT / "ghostea/services/upload_workflow.py").read_text(encoding="utf-8")
    states = set(re.findall(r'=\s*"([a-z_]+)"', workflow))
    expected = {
        "select_group","select_topic","select_source","wait_file","wait_url",
        "wait_caption","wait_description","wait_flag_image","wait_main_flag",
        "wait_sub_flags","wait_flag_description","confirm","ready","publishing",
        "cancelled","expired",
    }
    assert expected.issubset(states)
    # The DB intentionally does not use a hard-coded CHECK enum here; the
    # workflow service owns the state machine and Phase 9 adds durable indexes.
    assert "state not in ('cancelled', 'expired')" in sql


def test_database_client_has_schema_probe():
    s = (ROOT / "ghostea/storage/database.py").read_text(encoding="utf-8")
    assert "def check_tables(self, tables):" in s
    assert 'self.select(table, {"select": "*", "limit": "0"})' in s


def test_health_exposes_schema_status():
    s = (ROOT / "ghostea/web_server.py").read_text(encoding="utf-8")
    assert "required_tables" in s
    assert "ghostea_schema_meta" in s
    assert '"schema": {' in s
    assert "schema_ok" in s
