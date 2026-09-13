import re
import unittest
from pathlib import Path


class DashboardGroupIdValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (
            Path(__file__).resolve().parents[1] / "dashboard" / "index.html"
        ).read_text(encoding="utf-8")

    def test_frontend_accepts_negative_telegram_group_ids(self):
        match = re.search(r"if\(!(/\^.*?\$/)\.test\(raw\)", self.html)
        self.assertIsNotNone(match, "Group ID validation regex not found")
        pattern = match.group(1)
        self.assertEqual(pattern, r"/^-?\d{1,16}$/")

        validator = re.compile(r"^-?\d{1,16}$")
        for value in ("-1004382037144", "-123456789", "123456789"):
            self.assertIsNotNone(validator.fullmatch(value))

    def test_frontend_rejects_malformed_ids(self):
        validator = re.compile(r"^-?\d{1,16}$")
        for value in ("", "-", "--1004382037144", "12.3", "abc", "+100"):
            self.assertIsNone(validator.fullmatch(value))

    def test_mobile_input_preserves_leading_minus(self):
        self.assertIn(
            'id="groupIdInput" inputmode="text" placeholder="-1001234567890123"',
            self.html,
        )


if __name__ == "__main__":
    unittest.main()
