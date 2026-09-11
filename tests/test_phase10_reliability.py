from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_telegram_write_policy_only_retries_explicit_rate_limits():
    s=(ROOT/"ghostea/services/telegram_resilience.py").read_text()
    assert "call_write_rate_limited" in s
    assert 'failure.kind != "rate_limited"' in s


def test_resource_publish_has_per_session_lock():
    s=(ROOT/"ghostea/services/resource_publishing.py").read_text()
    assert "_publish_locks" in s
    assert "async with lock:" in s
    assert "claim_upload_for_publish" in s


def test_supabase_reliability_is_configurable():
    s=(ROOT/"ghostea/storage/database.py").read_text()
    assert "SUPABASE_HTTP_TIMEOUT_SECONDS" in s
    assert "SUPABASE_READ_RETRIES" in s
    assert "Retry-After" in s
    assert "random.uniform" in s


def test_phase10_requires_no_sql_migration():
    doc=(ROOT/"PHASE10_RELIABILITY.md").read_text()
    assert "No Phase 10 SQL migration is required." in doc
