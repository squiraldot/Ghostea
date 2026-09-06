import unittest
from pathlib import Path


class H11DashboardReliabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.server = (cls.root / "ghostea/web_server.py").read_text()
        cls.proxy = (cls.root / "dashboard/api/ghostea.js").read_text()
        cls.ui = (cls.root / "dashboard/index.html").read_text()
        cls.manager = (cls.root / "ghostea/services/user_management_service.py").read_text()

    def test_dashboard_uses_live_permission_service(self):
        self.assertIn("UserManagementService(store, bot, permission_service=permission_service)", self.server)
        self.assertIn("permission_service=permission_service", self.root.joinpath("ghostea/app.py").read_text())

    def test_auth_me_revalidates_current_admin(self):
        self.assertIn("self.admins.authorize(admin_id, role)", self.server)
        self.assertIn('"session_not_active"', self.server)

    def test_proxy_only_retries_reads(self):
        self.assertIn('const isRead = req.method === "GET"', self.proxy)
        self.assertIn("if (!isRead) throw error", self.proxy)
        self.assertIn("signal: controller.signal", self.proxy)

    def test_dashboard_api_only_retries_reads(self):
        self.assertIn("const read=method==='GET'", self.ui)
        self.assertIn("if(read&&[502,503,504].includes(r.status))r=await request()", self.ui)

    def test_mutations_invalidate_group_cache(self):
        self.assertIn('self._invalidate_cache("groups:")', self.server)

    def test_warning_reports_partial_punishment(self):
        self.assertIn('"result": "success" if not str(action).endswith("_failed") else "punishment_failed"', self.manager)
        self.assertIn("result.admin_action?.result==='punishment_failed'", self.ui)

    def test_dashboard_maps_telegram_failures_truthfully(self):
        self.assertIn('"telegram_action_failed"', self.server)
        self.assertIn('"bot_permission_unavailable"', self.server)
        self.assertIn('"target_is_admin"', self.server)


if __name__ == "__main__":
    unittest.main()
