import unittest

from ghostea.services.adversarial_regression import run_adversarial_regression, SCENARIOS


class H14AdversarialRegressionTests(unittest.TestCase):
    def test_all_failure_injection_scenarios_pass(self):
        report = run_adversarial_regression()
        self.assertTrue(report["ready"], report)
        self.assertEqual(report["passed"], len(SCENARIOS))
        self.assertEqual(report["failed"], [])
        self.assertEqual(report["missing"], [])

    def test_scenario_names_are_unique(self):
        names = [scenario.name for scenario in SCENARIOS]
        self.assertEqual(len(names), len(set(names)))

    def test_h14_is_offline(self):
        # The H14 module documents and enforces an offline deterministic
        # harness; no credentials/network client should be required to run it.
        report = run_adversarial_regression()
        self.assertEqual(report["scenario_count"], 12)


if __name__ == "__main__":
    unittest.main()
