import os
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from ghostea.services.deployment_profile import load_deployment_profile
from ghostea.storage.database import SupabaseREST
from ghostea.storage.postgresql import _json_safe, build_select_query, PostgreSQL
from ghostea.storage.provider_factory import create_database_provider
from ghostea.storage.providers import DatabaseProvider


class Phase20DatabaseProviderTests(unittest.TestCase):
    def test_provider_contract_has_required_operations(self):
        for name in ("select", "insert", "upsert", "update", "delete", "check_tables", "count", "close"):
            self.assertTrue(hasattr(DatabaseProvider, name))

    def test_postgres_values_match_postgrest_json_shapes(self):
        value = {
            "created_at": datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
            "id": UUID("12345678-1234-5678-1234-567812345678"),
            "amount": Decimal("12.50"),
            "whole": Decimal("12"),
            "nested": [Decimal("1.25"), {"when": datetime(2026, 1, 2)}],
        }
        result = _json_safe(value)
        self.assertEqual(result["created_at"], "2026-01-02T03:04:05+00:00")
        self.assertEqual(result["id"], "12345678-1234-5678-1234-567812345678")
        self.assertEqual(result["amount"], 12.5)
        self.assertEqual(result["whole"], 12)
        self.assertEqual(result["nested"], [1.25, {"when": "2026-01-02T00:00:00"}])

    def test_postgres_filter_translation_preserves_negative_telegram_ids(self):
        sql, params = build_select_query("ghostea_chat_registry", {
            "chat_id": "eq.-100987654321",
            "visibility": "eq.public",
            "limit": "1",
        })
        self.assertIn('"chat_id" = %s', sql)
        self.assertEqual(params, [-100987654321, "public", 1])

    def test_postgres_provider_is_lazy(self):
        old = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = "postgresql://ghostea:test@localhost:5432/ghostea"
        try:
            db = PostgreSQL()
            self.assertFalse(hasattr(db, "_connection"))
            db.close()
        finally:
            if old is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = old

    def test_managed_and_self_hosted_select_different_db_providers(self):
        managed = load_deployment_profile({
            "GHOSTEA_DEPLOYMENT_MODE": "managed",
            "GHOSTEA_DATABASE_PROVIDER": "supabase_rest",
            "GHOSTEA_STORAGE_PROVIDER": "supabase",
            "GHOSTEA_DASHBOARD_HOST": "vercel",
        })
        selfhost = load_deployment_profile({
            "GHOSTEA_DEPLOYMENT_MODE": "self_hosted",
            "GHOSTEA_DATABASE_PROVIDER": "postgresql",
            "GHOSTEA_STORAGE_PROVIDER": "local",
            "GHOSTEA_DASHBOARD_HOST": "vps",
        })
        self.assertEqual(managed.validate(), [])
        self.assertEqual(selfhost.validate(), [])
        old = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = "postgresql://ghostea:test@localhost:5432/ghostea"
        try:
            self.assertIsInstance(create_database_provider(selfhost), PostgreSQL)
        finally:
            if old is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = old
        self.assertIsInstance(SupabaseREST("https://example.supabase.co", "x"), SupabaseREST)


if __name__ == "__main__":
    unittest.main()
