from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(name):
    return (ROOT / name).read_text(encoding="utf-8")


def test_database_has_topic_id_preflight_before_topic_indexes():
    sql = read("database.sql")
    preflight = sql.index("Legacy deployment preflight")
    topic_index = sql.index("idx_ghostea_moderation_logs_chat_topic_time")
    assert preflight < topic_index


def test_database_repair_script_is_idempotent_and_schema_qualified():
    sql = read("DATABASE_REPAIR_TOPIC_ID.sql")
    assert "alter table public.ghostea_moderation_logs" in sql
    assert "add column if not exists topic_id bigint" in sql
    assert "idx_ghostea_moderation_logs_chat_topic_time" in sql


def test_render_startup_does_not_hard_fail_on_missing_bootstrap_password():
    app = read("ghostea/app.py")
    assert 'GHOSTEA_ADMIN_PASSWORD is required.' not in app
    assert "first dashboard Super Admin" in app and "bootstrap" in app


def test_admin_bootstrap_does_not_require_secret_for_existing_account():
    admin = read("ghostea/services/admin_service.py")
    assert "if rows:\n            return" in admin
    assert "if not password:\n            return" in admin
