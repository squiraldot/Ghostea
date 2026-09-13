import unittest
from ghostea.services.deployment_matrix import is_supported, matrix_rows
from ghostea.services.deployment_setup import build_setup_result

BASE = {
    "BOT_TOKEN": "x", "DASHBOARD_API_KEY": "a"*32,
    "DASHBOARD_ORIGIN": "https://dashboard.example.com",
    "GHOSTEA_PROXY_SIGNING_SECRET": "b"*32,
}

class Phase25DeploymentMatrixTests(unittest.TestCase):
    def test_matrix_covers_all_provider_axes(self):
        self.assertEqual(len(matrix_rows()), 2 * 3 * 3)
        self.assertTrue(is_supported("postgresql", "s3", "vercel"))
        self.assertTrue(is_supported("supabase_rest", "local", "vps"))

    def test_bad_supabase_url_fails_before_network(self):
        env = dict(BASE, SUPABASE_URL="not-a-url", SUPABASE_KEY="key")
        r = build_setup_result(env, "custom", database="supabase_rest", storage="supabase", dashboard="external")
        self.assertFalse(r.ready)
        self.assertTrue(any("SUPABASE_URL must be an absolute http(s) URL" in e for e in r.errors))

    def test_bad_postgres_url_fails_closed(self):
        env = dict(BASE, DATABASE_URL="https://not-postgres")
        r = build_setup_result(env, "custom", database="postgresql", storage="local", dashboard="external")
        self.assertFalse(r.ready)
        self.assertTrue(any("DATABASE_URL must be a valid postgres" in e for e in r.errors))

    def test_bad_s3_bucket_and_endpoint(self):
        env = dict(BASE, GHOSTEA_S3_BUCKET="BAD_BUCKET!", GHOSTEA_S3_ACCESS_KEY="a", GHOSTEA_S3_SECRET_KEY="b", GHOSTEA_S3_ENDPOINT_URL="ftp://bad")
        r = build_setup_result(env, "custom", database="postgresql", storage="s3", dashboard="external")
        self.assertFalse(r.ready)
        self.assertTrue(any("GHOSTEA_S3_BUCKET" in e for e in r.errors))
        self.assertTrue(any("GHOSTEA_S3_ENDPOINT_URL" in e for e in r.errors))

    def test_valid_custom_topology(self):
        env = dict(BASE, DATABASE_URL="postgresql://u:p@db/ghostea", GHOSTEA_S3_BUCKET="ghostea-bucket", GHOSTEA_S3_ACCESS_KEY="a", GHOSTEA_S3_SECRET_KEY="b")
        r = build_setup_result(env, "custom", database="postgresql", storage="s3", dashboard="external")
        self.assertTrue(r.ready, r.errors)

if __name__ == "__main__": unittest.main()
