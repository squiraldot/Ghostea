import os
import threading
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer

from ghostea.web_server import DashboardHandler, _dashboard_make_session, _dashboard_session_from_request


class FakeAdmins:
    async def authenticate(self, username, password):
        if username == "admin" and password == "correct-password":
            return {"id": 7, "username": "admin", "display_name": "Admin", "role": "super_admin", "enabled": True}
        return None

    async def authorize(self, admin_id, role):
        if str(admin_id) == "7" and role == "super_admin":
            return {"id": 7, "username": "admin", "display_name": "Admin", "role": "super_admin", "enabled": True}
        return None

    def allowed(self, role, permission):
        return role == "super_admin"


class Phase21DashboardTests(unittest.TestCase):
    def setUp(self):
        self.env = dict(os.environ)
        os.environ.update({
            "GHOSTEA_DEPLOYMENT_MODE": "self_hosted",
            "GHOSTEA_DASHBOARD_HOST": "vps",
            "GHOSTEA_SESSION_SECRET": "s" * 48,
            "GHOSTEA_PROXY_SIGNING_SECRET": "p" * 48,
            "DASHBOARD_API_KEY": "k" * 48,
            "DASHBOARD_ORIGIN": "https://ghostea.example.com",
        })
        DashboardHandler.admins = FakeAdmins()
        DashboardHandler.store = None
        DashboardHandler.analytics = None
        DashboardHandler.risk = None
        DashboardHandler.permission_service = None
        DashboardHandler._async_loop = None

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), DashboardHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()
        os.environ.clear()
        os.environ.update(self.env)

    def request(self, method, path, body=None, headers=None):
        conn = HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        conn.request(method, path, body=body, headers=headers or {})
        response = conn.getresponse()
        data = response.read()
        cookies = response.getheader("Set-Cookie")
        conn.close()
        return response.status, data, cookies

    def test_vps_dashboard_serves_index(self):
        status, data, _ = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"Ghostea Admin", data)

    def test_session_is_signed_and_round_trips(self):
        token = _dashboard_make_session({"id": 7, "role": "super_admin", "username": "admin"})
        class Request:
            headers = {"Cookie": f"ghostea_session={token}"}
        session = _dashboard_session_from_request(Request())
        self.assertEqual(session["admin_id"], "7")
        self.assertEqual(session["role"], "super_admin")
        self.assertEqual(session["username"], "admin")

    def test_local_login_returns_session_cookie(self):
        body = '{"username":"admin","password":"correct-password"}'
        status, data, cookie = self.request("POST", "/api/ghostea?action=login", body, {"Content-Type": "application/json"})
        self.assertEqual(status, 200)
        self.assertIn(b'"ok": true', data)
        self.assertIn("ghostea_session=", cookie or "")
        self.assertIn("HttpOnly", cookie or "")
        self.assertIn("Secure", cookie or "")

    def test_local_proxy_rejects_without_session(self):
        status, data, _ = self.request("GET", "/api/ghostea?path=%2Fapi%2Fauth%2Fme")
        self.assertEqual(status, 401)
        self.assertIn(b"login_required", data)


if __name__ == "__main__":
    unittest.main()
