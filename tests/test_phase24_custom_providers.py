import os
import subprocess
import sys
import unittest

from ghostea.services.deployment_profile import load_deployment_profile
from ghostea.services.deployment_setup import build_setup_result, render_env_template, required_environment


BASE = {
    "BOT_TOKEN": "x",
    "DASHBOARD_API_KEY": "a" * 32,
    "DASHBOARD_ORIGIN": "https://dashboard.example.com",
    "GHOSTEA_PROXY_SIGNING_SECRET": "b" * 32,
}


class Phase24CustomProviderTests(unittest.TestCase):
    def test_custom_render_postgres_s3_vercel(self):
        env = dict(BASE, DATABASE_URL="postgresql://u:p@db/ghostea",
                   GHOSTEA_S3_BUCKET="ghostea", GHOSTEA_S3_ACCESS_KEY="access",
                   GHOSTEA_S3_SECRET_KEY="secret")
        result = build_setup_result(env, "custom", database="postgresql", storage="s3", dashboard="vercel")
        self.assertTrue(result.ready, result.errors)
        self.assertEqual(result.profile.mode, "custom")
        self.assertEqual(result.profile.database_provider, "postgresql")
        self.assertEqual(result.profile.storage_provider, "s3")
        self.assertEqual(result.profile.dashboard_host, "vercel")
        self.assertIn("GHOSTEA_S3_BUCKET", required_environment(result.profile))
        template = render_env_template("custom", database="postgresql", storage="s3", dashboard="vercel")
        self.assertIn("DATABASE_URL=", template)
        self.assertIn("GHOSTEA_S3_BUCKET=", template)
        self.assertNotIn("GHOSTEA_S3_SECRET_KEY=secret", template)

    def test_custom_postgres_supabase_vps(self):
        env = dict(BASE, DATABASE_URL="postgresql://u:p@db/ghostea",
                   SUPABASE_URL="https://project.supabase.co", SUPABASE_KEY="server-key",
                   GHOSTEA_SESSION_SECRET="c" * 32)
        result = build_setup_result(env, "custom", database="postgresql", storage="supabase", dashboard="vps")
        self.assertTrue(result.ready, result.errors)

    def test_custom_supabase_s3_vps(self):
        env = dict(BASE, SUPABASE_URL="https://project.supabase.co", SUPABASE_KEY="server-key",
                   GHOSTEA_S3_BUCKET="ghostea", GHOSTEA_S3_ACCESS_KEY="access",
                   GHOSTEA_S3_SECRET_KEY="secret", GHOSTEA_SESSION_SECRET="c" * 32)
        result = build_setup_result(env, "custom", database="supabase_rest", storage="s3", dashboard="vps")
        self.assertTrue(result.ready, result.errors)

    def test_custom_without_provider_selection_fails_closed(self):
        result = build_setup_result(BASE, "custom")
        self.assertFalse(result.ready)
        self.assertTrue(any("Custom profile requires GHOSTEA_DATABASE_PROVIDER" in e for e in result.errors))
        self.assertTrue(any("Custom profile requires GHOSTEA_STORAGE_PROVIDER" in e for e in result.errors))
        self.assertTrue(any("Custom profile requires GHOSTEA_DASHBOARD_HOST" in e for e in result.errors))

    def test_setup_cli_runs_from_repository_root(self):
        proc = subprocess.run(
            [sys.executable, "scripts/ghostea_setup.py", "--profile", "custom",
             "--database", "postgresql", "--storage", "s3", "--dashboard", "vercel",
             "--show-template"],
            env=dict(os.environ), capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("GHOSTEA_DATABASE_PROVIDER=postgresql", proc.stdout)
        self.assertNotIn("ModuleNotFoundError", proc.stderr)

    def test_canonical_profiles_remain_strict(self):
        p = load_deployment_profile({
            "GHOSTEA_DEPLOYMENT_MODE": "managed",
            "GHOSTEA_DATABASE_PROVIDER": "postgresql",
            "GHOSTEA_STORAGE_PROVIDER": "s3",
            "GHOSTEA_DASHBOARD_HOST": "vercel",
        })
        errors = p.validate()
        self.assertIn("managed requires GHOSTEA_DATABASE_PROVIDER=supabase_rest", errors)
        self.assertIn("managed requires GHOSTEA_STORAGE_PROVIDER=supabase", errors)


if __name__ == "__main__":
    unittest.main()
