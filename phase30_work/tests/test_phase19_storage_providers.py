import os
import unittest
from unittest.mock import patch

from ghostea.services.deployment_profile import load_deployment_profile
from ghostea.storage.provider_factory import create_storage_provider
from ghostea.storage.remote import S3CompatibleStorage, SupabaseStorage


class _FakeBody:
    def __init__(self, data): self.data = data
    def read(self): return self.data


class _FakeS3:
    def __init__(self):
        self.objects = {}
    def put_object(self, **kwargs):
        body = kwargs["Body"].read()
        self.objects[(kwargs["Bucket"], kwargs["Key"])] = body
    def get_object(self, **kwargs):
        key=(kwargs["Bucket"], kwargs["Key"])
        if key not in self.objects:
            err=RuntimeError("missing")
            err.response={"ResponseMetadata":{"HTTPStatusCode":404}}
            raise err
        return {"Body": _FakeBody(self.objects[key])}
    def delete_object(self, **kwargs):
        self.objects.pop((kwargs["Bucket"], kwargs["Key"]), None)
    def head_object(self, **kwargs):
        if (kwargs["Bucket"], kwargs["Key"]) not in self.objects:
            err=RuntimeError("missing")
            err.response={"ResponseMetadata":{"HTTPStatusCode":404}}
            raise err


class Phase19StorageProviderTests(unittest.TestCase):
    def test_managed_supabase_factory_returns_real_provider(self):
        p=load_deployment_profile({
            "GHOSTEA_DEPLOYMENT_MODE":"managed",
            "GHOSTEA_DATABASE_PROVIDER":"supabase_rest",
            "GHOSTEA_STORAGE_PROVIDER":"supabase",
            "GHOSTEA_DASHBOARD_HOST":"vercel",
        })
        s=create_storage_provider(p, supabase_url="https://example.supabase.co", supabase_key="secret")
        self.assertIsInstance(s, SupabaseStorage)

    def test_s3_roundtrip_with_injected_client(self):
        fake=_FakeS3()
        s=S3CompatibleStorage("bucket","ak","sk",client=fake,max_bytes=10)
        self.assertEqual(s.put("resources/r/a.bin", b"hello"), "resources/r/a.bin")
        self.assertTrue(s.exists("resources/r/a.bin"))
        self.assertEqual(s.get("resources/r/a.bin"), b"hello")
        self.assertTrue(s.delete("resources/r/a.bin"))
        self.assertFalse(s.exists("resources/r/a.bin"))

    def test_remote_keys_reject_traversal(self):
        s=S3CompatibleStorage("bucket","ak","sk",client=_FakeS3())
        with self.assertRaises(ValueError):
            s.put("../escape", b"x")

    def test_s3_factory_requires_credentials(self):
        p=load_deployment_profile({
            "GHOSTEA_DEPLOYMENT_MODE":"managed",
            "GHOSTEA_DATABASE_PROVIDER":"supabase_rest",
            "GHOSTEA_STORAGE_PROVIDER":"s3",
            "GHOSTEA_DASHBOARD_HOST":"vercel",
        })
        with patch.dict(os.environ, {
            "GHOSTEA_S3_BUCKET":"","GHOSTEA_S3_ACCESS_KEY":"","GHOSTEA_S3_SECRET_KEY":""
        }, clear=False):
            with self.assertRaises(RuntimeError):
                create_storage_provider(p)


if __name__ == "__main__":
    unittest.main()
