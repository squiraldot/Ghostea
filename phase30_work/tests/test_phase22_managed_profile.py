import os
import unittest
from pathlib import Path
from ghostea.services.deployment_profile import load_deployment_profile
from ghostea.services.production_readiness import local_readiness

class Phase22ManagedProfileTests(unittest.TestCase):
    def test_managed_canonical_profile_is_valid(self):
        p=load_deployment_profile({
            "GHOSTEA_DEPLOYMENT_MODE":"managed",
            "GHOSTEA_DATABASE_PROVIDER":"supabase_rest",
            "GHOSTEA_STORAGE_PROVIDER":"supabase",
            "GHOSTEA_DASHBOARD_HOST":"vercel",
        })
        self.assertEqual(p.validate(), [])

    def test_managed_rejects_incomplete_provider_mix(self):
        p=load_deployment_profile({
            "GHOSTEA_DEPLOYMENT_MODE":"managed",
            "GHOSTEA_DATABASE_PROVIDER":"postgresql",
            "GHOSTEA_STORAGE_PROVIDER":"local",
            "GHOSTEA_DASHBOARD_HOST":"vps",
        })
        self.assertTrue(p.validate())

    def test_managed_uses_default_storage_bucket(self):
        old = dict(os.environ)
        try:
            os.environ.clear()
            os.environ.update({
                "BOT_TOKEN":"x", "DASHBOARD_API_KEY":"k"*48,
                "DASHBOARD_ORIGIN":"https://ghostea.vercel.app",
                "GHOSTEA_PROXY_SIGNING_SECRET":"p"*48,
                "GHOSTEA_DEPLOYMENT_MODE":"managed",
                "GHOSTEA_DATABASE_PROVIDER":"supabase_rest",
                "GHOSTEA_STORAGE_PROVIDER":"supabase",
                "GHOSTEA_DASHBOARD_HOST":"vercel",
                "SUPABASE_URL":"https://example.supabase.co",
                "SUPABASE_KEY":"x"*48,
            })
            checks={c.name:c for c in local_readiness(Path.cwd())}
            self.assertTrue(checks["supabase_storage_bucket_policy"].ok)
        finally:
            os.environ.clear(); os.environ.update(old)

    def test_self_hosted_does_not_require_explicit_local_storage_root(self):
        p=load_deployment_profile({
            "GHOSTEA_DEPLOYMENT_MODE":"self_hosted",
            "GHOSTEA_DATABASE_PROVIDER":"postgresql",
            "GHOSTEA_STORAGE_PROVIDER":"local",
            "GHOSTEA_DASHBOARD_HOST":"vps",
        })
        self.assertEqual(p.validate(), [])

    def test_readiness_requires_vps_session_secret(self):
        old=dict(os.environ)
        try:
            os.environ.clear()
            os.environ.update({
                "BOT_TOKEN":"x",
                "DASHBOARD_API_KEY":"k"*48,
                "DASHBOARD_ORIGIN":"https://ghostea.example.com",
                "GHOSTEA_PROXY_SIGNING_SECRET":"p"*48,
                "GHOSTEA_DEPLOYMENT_MODE":"self_hosted",
                "GHOSTEA_DATABASE_PROVIDER":"postgresql",
                "GHOSTEA_STORAGE_PROVIDER":"local",
                "GHOSTEA_DASHBOARD_HOST":"vps",
                "DATABASE_URL":"postgresql://ghostea:test@localhost:5432/ghostea",
            })
            checks={c.name:c for c in local_readiness(Path.cwd())}
            self.assertFalse(checks["GHOSTEA_SESSION_SECRET"].ok)
            os.environ["GHOSTEA_SESSION_SECRET"]="s"*48
            checks={c.name:c for c in local_readiness(Path.cwd())}
            self.assertTrue(checks["GHOSTEA_SESSION_SECRET"].ok)
            self.assertTrue(checks["dashboard_session_secret_entropy"].ok)
        finally:
            os.environ.clear(); os.environ.update(old)

if __name__=="__main__":
    unittest.main()
