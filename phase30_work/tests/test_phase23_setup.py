import os
import subprocess
import sys
import unittest
from pathlib import Path

from ghostea.services.deployment_setup import (
    build_setup_result, profile_template, render_env_template
)


class Phase23SetupTests(unittest.TestCase):
    def test_managed_template(self):
        self.assertEqual(profile_template("managed")["GHOSTEA_DATABASE_PROVIDER"], "supabase_rest")
        self.assertIn("SUPABASE_URL=", render_env_template("managed"))
        self.assertNotIn("SUPABASE_KEY=secret", render_env_template("managed"))

    def test_self_hosted_template(self):
        self.assertEqual(profile_template("self_hosted")["GHOSTEA_STORAGE_PROVIDER"], "local")
        self.assertIn("DATABASE_URL=", render_env_template("self_hosted"))
        self.assertIn("GHOSTEA_SESSION_SECRET=", render_env_template("self_hosted"))

    def test_missing_environment_is_reported_without_secret_values(self):
        env = {"BOT_TOKEN": "x", "DASHBOARD_API_KEY": "a"*32,
               "DASHBOARD_ORIGIN": "https://example.com",
               "GHOSTEA_PROXY_SIGNING_SECRET": "b"*32}
        result = build_setup_result(env, "managed")
        self.assertFalse(result.ready)
        self.assertIn("Missing required environment variable: SUPABASE_URL", result.errors)
        self.assertNotIn("b"*32, " ".join(result.errors))

    def test_complete_self_hosted_profile(self):
        env = {
            "BOT_TOKEN": "x", "DASHBOARD_API_KEY": "a"*32,
            "DASHBOARD_ORIGIN": "https://example.com",
            "GHOSTEA_PROXY_SIGNING_SECRET": "b"*32,
            "DATABASE_URL": "postgresql://user:pass@localhost:5432/ghostea",
            "GHOSTEA_SESSION_SECRET": "c"*32,
        }
        result = build_setup_result(env, "self_hosted")
        self.assertTrue(result.ready)

    def test_malformed_integer_env_does_not_crash_config_import(self):
        code = "import ghostea.config; print(ghostea.config.GHOSTEA_LOCAL_STORAGE_MAX_BYTES)"
        env = dict(os.environ, GHOSTEA_LOCAL_STORAGE_MAX_BYTES="not-a-number")
        proc = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(proc.stdout.strip().isdigit())


if __name__ == "__main__":
    unittest.main()
