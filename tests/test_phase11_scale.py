from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_phase11_sql_has_hot_path_indexes_and_is_idempotent():
    sql=(ROOT/"database.sql").read_text()
    assert "-- PHASE 11" in sql
    for name in (
        "idx_ghostea_moderation_logs_chat_created",
        "idx_ghostea_moderation_logs_chat_user_created",
        "idx_ghostea_user_directory_chat_activity",
        "idx_ghostea_join_events_chat_created",
        "idx_ghostea_topic_registry_chat_active_updated",
        "idx_ghostea_resources_chat_topic_created",
    ):
        assert f"CREATE INDEX IF NOT EXISTS {name}" in sql


def test_user_directory_touch_window_is_configurable_and_bounded():
    s=(ROOT/"ghostea/storage/phase3_store.py").read_text()
    assert "GHOSTEA_USER_DIRECTORY_TOUCH_SECONDS" in s
    assert "max(30.0" in s


def test_store_list_queries_are_bounded():
    s=(ROOT/"ghostea/storage/phase3_store.py").read_text()
    assert "min(int(limit), 200)" in s or "min(int(limit), 500)" in s
