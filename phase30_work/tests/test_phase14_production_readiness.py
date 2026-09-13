import os
import unittest
from pathlib import Path

from ghostea.services.production_readiness import local_readiness


class Phase14ProductionReadinessTests(unittest.TestCase):
    def setUp(self):
        self.saved = {k: os.environ.get(k) for k in (
            "BOT_TOKEN", "SUPABASE_URL", "SUPABASE_KEY",
            "DASHBOARD_API_KEY", "DASHBOARD_ORIGIN",
            "GHOSTEA_PROXY_SIGNING_SECRET",
        )}
        os.environ.update({
            "BOT_TOKEN": "test-bot-token",
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_KEY": "k" * 40,
            "DASHBOARD_API_KEY": "a" * 40,
            "DASHBOARD_ORIGIN": "https://dashboard.example.com",
            "GHOSTEA_PROXY_SIGNING_SECRET": "p" * 40,
        })

    def tearDown(self):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _checks(self):
        return {c.name: c for c in local_readiness(Path(__file__).resolve().parents[1])}

    def test_strong_production_configuration_passes_policy(self):
        checks = self._checks()
        self.assertTrue(checks["GHOSTEA_PROXY_SIGNING_SECRET"].ok)
        self.assertTrue(checks["dashboard_api_key_entropy"].ok)
        self.assertTrue(checks["proxy_signing_secret_entropy"].ok)
        self.assertTrue(checks["dashboard_origin_policy"].ok)
        self.assertTrue(checks["supabase_url_policy"].ok)

    def test_short_proxy_secret_fails_without_revealing_value(self):
        os.environ["GHOSTEA_PROXY_SIGNING_SECRET"] = "short"
        checks = self._checks()
        self.assertFalse(checks["proxy_signing_secret_entropy"].ok)
        self.assertNotIn("short", checks["proxy_signing_secret_entropy"].detail)

    def test_http_dashboard_origin_is_rejected_in_production_style_check(self):
        os.environ["DASHBOARD_ORIGIN"] = "http://dashboard.example.com"
        checks = self._checks()
        self.assertFalse(checks["dashboard_origin_policy"].ok)


if __name__ == "__main__":
    unittest.main()
