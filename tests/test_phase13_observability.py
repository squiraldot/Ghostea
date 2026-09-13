import unittest

from ghostea.services.observability import Observability, set_request_id, reset_request_id


class Phase13ObservabilityTests(unittest.TestCase):
    def test_recursive_secret_redaction_and_bounded_strings(self):
        obs = Observability(max_events=100)
        token = set_request_id("test_123")
        try:
            event = obs.emit(
                "security_probe",
                authorization="Bearer SECRET",
                nested={"password": "secret", "ok": "x" * 600},
            )
        finally:
            reset_request_id(token)

        self.assertNotIn("authorization", event)
        self.assertNotIn("password", str(event))
        self.assertLessEqual(len(event["nested"]["ok"]), 501)

    def test_duration_metrics_are_aggregated(self):
        obs = Observability(max_events=100)
        obs.observe_duration("http_request", 0.010)
        obs.observe_duration("http_request", 0.020)
        snap = obs.snapshot(10)
        metric = snap["durations"]["http_request"]
        self.assertEqual(metric["count"], 2)
        self.assertAlmostEqual(metric["avg_ms"], 15.0, places=3)
        self.assertAlmostEqual(metric["max_ms"], 20.0, places=3)

    def test_diagnostics_snapshot_contains_durations(self):
        obs = Observability(max_events=100)
        obs.observe_duration("supabase_request", 0.001)
        snap = obs.snapshot(5)
        self.assertIn("durations", snap)
        self.assertIn("supabase_request", snap["durations"])


if __name__ == "__main__":
    unittest.main()
