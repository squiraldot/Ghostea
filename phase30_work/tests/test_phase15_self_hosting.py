import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class Phase15SelfHostingTests(unittest.TestCase):
    def test_container_artifacts_exist(self):
        for name in ("Dockerfile", ".dockerignore", "docker-compose.selfhost.yml"):
            self.assertTrue((ROOT / name).is_file(), name)

    def test_systemd_unit_has_hardening(self):
        text = (ROOT / "deploy/systemd/ghostea.service").read_text()
        for token in (
            "NoNewPrivileges=true",
            "ProtectSystem=strict",
            "ProtectHome=true",
            "PrivateTmp=true",
            "Restart=always",
        ):
            self.assertIn(token, text)

    def test_compose_has_unprivileged_container_controls(self):
        text = (ROOT / "docker-compose.selfhost.yml").read_text()
        for token in (
            "read_only: true",
            "no-new-privileges:true",
            "cap_drop:",
            "ALL",
            "ghostea-data:/app/data",
        ):
            self.assertIn(token, text)

    def test_nginx_proxies_self_hosted_dashboard_and_api(self):
        text = (ROOT / "deploy/nginx/ghostea.conf").read_text()
        self.assertIn("location / {", text)
        self.assertIn("proxy_pass http://127.0.0.1:10000;", text)
        self.assertIn("location /api/ {", text)


if __name__ == "__main__":
    unittest.main()
