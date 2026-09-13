import unittest

from ghostea.services.deployment_profile import load_deployment_profile
from ghostea.storage.provider_factory import create_storage_provider
from ghostea.storage.local import LocalStorage


class Phase18StorageIntegrationTests(unittest.TestCase):
    def test_self_hosted_factory_returns_local_storage(self):
        profile = load_deployment_profile({
            "GHOSTEA_DEPLOYMENT_MODE": "self_hosted",
            "GHOSTEA_DATABASE_PROVIDER": "postgresql",
            "GHOSTEA_STORAGE_PROVIDER": "local",
            "GHOSTEA_DASHBOARD_HOST": "vps",
        })
        storage = create_storage_provider(profile)
        self.assertIsInstance(storage, LocalStorage)

    def test_managed_factory_keeps_existing_remote_path_untouched(self):
        profile = load_deployment_profile({
            "GHOSTEA_DEPLOYMENT_MODE": "managed",
            "GHOSTEA_DATABASE_PROVIDER": "supabase_rest",
            "GHOSTEA_STORAGE_PROVIDER": "supabase",
            "GHOSTEA_DASHBOARD_HOST": "vercel",
        })
        self.assertIsInstance(create_storage_provider(profile, supabase_url="https://example.supabase.co", supabase_key="secret"), __import__("ghostea.storage.remote", fromlist=["SupabaseStorage"]).SupabaseStorage)


if __name__ == "__main__":
    unittest.main()
