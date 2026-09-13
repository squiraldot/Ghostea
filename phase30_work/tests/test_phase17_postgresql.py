import unittest

from ghostea.services.deployment_profile import load_deployment_profile
from ghostea.storage.postgresql import build_select_query, PostgreSQL
from ghostea.storage.provider_factory import create_database_provider


class Phase17PostgreSQLTests(unittest.TestCase):
    def test_self_hosted_profile_is_valid(self):
        p = load_deployment_profile({
            "GHOSTEA_DEPLOYMENT_MODE": "self_hosted",
            "GHOSTEA_DATABASE_PROVIDER": "postgresql",
            "GHOSTEA_STORAGE_PROVIDER": "local",
            "GHOSTEA_DASHBOARD_HOST": "vps",
        })
        self.assertEqual(p.validate(), [])

    def test_select_translation(self):
        sql, params = build_select_query("ghostea_warnings", {
            "chat_id": "eq.-100123",
            "user_id": "eq.42",
            "order": "updated_at.desc",
            "limit": "10",
        })
        self.assertIn('FROM "ghostea_warnings"', sql)
        self.assertIn('"chat_id" = %s', sql)
        self.assertIn('"user_id" = %s', sql)
        self.assertIn("ORDER BY", sql)
        self.assertEqual(params, [-100123, 42, 10])

    def test_not_in_and_in_filters(self):
        sql, params = build_select_query("ghostea_upload_sessions", {
            "state": "not.in.(cancelled,expired,ready)",
            "chat_id": "in.(-1001,-1002)",
        })
        self.assertIn('NOT IN (%s, %s, %s)', sql)
        self.assertIn('IN (%s, %s)', sql)
        self.assertEqual(params, ["cancelled", "expired", "ready", -1001, -1002])

    def test_json_columns_are_not_allowed_as_identifiers(self):
        with self.assertRaises(ValueError):
            build_select_query("ghostea_resources", {"payload->>x": "eq.foo"})

    def test_factory_selects_postgresql_without_connecting_until_used(self):
        p = load_deployment_profile({
            "GHOSTEA_DEPLOYMENT_MODE": "self_hosted",
            "GHOSTEA_DATABASE_PROVIDER": "postgresql",
            "GHOSTEA_STORAGE_PROVIDER": "local",
            "GHOSTEA_DASHBOARD_HOST": "vps",
        })
        import os
        old = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = "postgresql://ghostea:test@localhost:5432/ghostea"
        try:
            db = create_database_provider(p)
            self.assertIsInstance(db, PostgreSQL)
        finally:
            if old is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = old

    def test_unknown_table_is_rejected(self):
        with self.assertRaises(ValueError):
            build_select_query("users;drop", {"id": "eq.1"})


if __name__ == "__main__":
    unittest.main()
