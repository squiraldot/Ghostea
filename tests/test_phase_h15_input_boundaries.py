import unittest

from ghostea.services.input_boundary import run_input_boundary_regression, SCENARIOS


class H15InputBoundaryTests(unittest.TestCase):
    def test_all_boundary_scenarios_pass(self):
        report = run_input_boundary_regression()
        self.assertTrue(report["ready"], report)
        self.assertEqual(report["passed"], len(SCENARIOS))
        self.assertEqual(report["failed"], [])
        self.assertEqual(report["missing"], [])

    def test_scenario_names_are_unique(self):
        names = [x.name for x in SCENARIOS]
        self.assertEqual(len(names), len(set(names)))

    def test_h15_is_offline(self):
        self.assertEqual(run_input_boundary_regression()["scenario_count"], 10)


if __name__ == "__main__":
    unittest.main()
