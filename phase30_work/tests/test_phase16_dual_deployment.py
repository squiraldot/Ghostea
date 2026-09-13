import unittest
from ghostea.services.deployment_profile import load_deployment_profile

class Phase16DualDeploymentTests(unittest.TestCase):
    def test_managed_profile_is_default_and_valid(self):
        p = load_deployment_profile({})
        self.assertEqual((p.mode, p.database_provider, p.storage_provider, p.dashboard_host),
                         ("managed", "supabase_rest", "supabase", "vercel"))
        self.assertEqual(p.validate(), [])

    def test_self_hosted_profile_is_explicit(self):
        p = load_deployment_profile({
            "GHOSTEA_DEPLOYMENT_MODE": "self_hosted",
            "GHOSTEA_DATABASE_PROVIDER": "postgresql",
            "GHOSTEA_STORAGE_PROVIDER": "local",
            "GHOSTEA_DASHBOARD_HOST": "vps",
        })
        self.assertTrue(p.is_self_hosted)
        self.assertEqual(p.validate(), [])

    def test_self_hosted_cannot_silently_use_cloud_database(self):
        p = load_deployment_profile({
            "GHOSTEA_DEPLOYMENT_MODE": "self_hosted",
            "GHOSTEA_DATABASE_PROVIDER": "supabase_rest",
            "GHOSTEA_STORAGE_PROVIDER": "local",
            "GHOSTEA_DASHBOARD_HOST": "vps",
        })
        self.assertIn("self_hosted requires GHOSTEA_DATABASE_PROVIDER=postgresql", p.validate())

    def test_unknown_provider_fails_validation(self):
        p = load_deployment_profile({"GHOSTEA_DATABASE_PROVIDER": "mysql"})
        self.assertTrue(any("Unsupported GHOSTEA_DATABASE_PROVIDER" in e for e in p.validate()))

if __name__ == "__main__":
    unittest.main()
