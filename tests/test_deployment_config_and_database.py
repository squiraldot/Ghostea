import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(name):
    return (ROOT / name).read_text(encoding="utf-8")


def test_legacy_warning_history_column_is_added_before_indexes():
    sql = _read("database.sql")
    alter = sql.index(
        "alter table ghostea_warning_history\n  add column if not exists active"
    )
    active_index = sql.index("idx_ghostea_warning_history_active")
    assert alter < active_index


def test_legacy_moderation_topic_column_is_added_before_topic_indexes():
    sql = _read("database.sql")
    alter = sql.index(
        "alter table ghostea_moderation_logs\n  add column if not exists topic_id"
    )
    topic_index = sql.index("idx_ghostea_moderation_logs_chat_topic_time")
    topic_user_index = sql.index("idx_ghostea_moderation_logs_chat_topic_user_time")
    assert alter < topic_index < topic_user_index


def test_render_required_environment_contract():
    render = _read("render.yaml")
    expected = {
        "BOT_TOKEN",
        "SUPABASE_URL",
        "SUPABASE_KEY",
        "DASHBOARD_API_KEY",
        "DASHBOARD_ORIGIN",
        "GHOSTEA_ADMIN_PASSWORD",
        "GHOSTEA_SUPERADMIN_USERNAME",
    }
    actual = set(re.findall(r"^\s+- key: ([A-Z0-9_]+)\s*$", render, re.M))
    assert expected <= actual


def test_vercel_proxy_environment_contract_is_three_variables():
    js = _read("dashboard/api/ghostea.js")
    for name in ("GHOSTEA_API_URL", "GHOSTEA_API_KEY", "GHOSTEA_SESSION_SECRET"):
        assert f'secret("{name}")' in js
    assert 'secret("GHOSTEA_ADMIN_PASSWORD")' not in js


def test_env_example_does_not_mislabel_render_bootstrap_secrets_as_vercel():
    env = _read(".env.example")
    vercel_section = env.split("# Render only", 1)[0]
    assert "GHOSTEA_SUPERADMIN_USERNAME" not in vercel_section
    assert "GHOSTEA_ADMIN_PASSWORD" not in vercel_section
