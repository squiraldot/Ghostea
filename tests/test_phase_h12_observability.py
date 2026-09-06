import unittest
from pathlib import Path

class H12ObservabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=Path(__file__).resolve().parents[1]
        cls.obs=(cls.root/"ghostea/services/observability.py").read_text()
        cls.action=(cls.root/"ghostea/services/action_result.py").read_text()
        cls.app=(cls.root/"ghostea/app.py").read_text()
        cls.web=(cls.root/"ghostea/web_server.py").read_text()
        cls.events=(cls.root/"ghostea/handlers/permission_events.py").read_text()

    def test_observability_is_bounded_and_redacts_secrets(self):
        self.assertIn("deque(maxlen=self.max_events)", self.obs)
        self.assertIn('"authorization"', self.obs)
        self.assertIn("OBSERVABILITY", self.action)

    def test_update_correlation_context(self):
        self.assertIn('new_request_id("tg")', self.app)
        self.assertIn('"update_received"', self.app)
        self.assertIn('"duplicate_update"', self.app)

    def test_lifecycle_events_are_observable(self):
        self.assertIn('"bot_membership_change"', self.events)
        self.assertIn('"member_status_change"', self.events)

    def test_http_diagnostics_and_request_ids(self):
        self.assertIn('new_request_id("http")', self.web)
        self.assertIn('path == "/api/diagnostics"', self.web)
        self.assertIn("OBSERVABILITY.snapshot(limit)", self.web)

if __name__=="__main__":
    unittest.main()
