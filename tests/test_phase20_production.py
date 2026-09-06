import os
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from ghostea.services.chat_capabilities import resolve_chat_capabilities
from ghostea.services.chat_context import ChatContext
from ghostea.services.production_readiness import compatibility_matrix, readiness_summary, local_readiness


class Phase20ProductionTests(unittest.TestCase):
    def test_compatibility_matrix_covers_all_supported_modes(self):
        matrix = compatibility_matrix()
        kinds = {row["kind"] for row in matrix}
        self.assertIn("group", kinds)
        self.assertIn("supergroup", kinds)
        self.assertIn("forum_supergroup", kinds)
        self.assertIn("unsupported", {"unsupported", *kinds})
        private_topic = next(r for r in matrix if r["kind"] == "unsupported" and r["topic_messages"])
        self.assertFalse(private_topic["supports_moderation"])

    def test_forum_and_private_topic_boundaries_are_distinct(self):
        forum = ChatContext(1, "supergroup", "", None, False, True, True, 42, "private", False)
        private = ChatContext(2, "private", "", None, False, False, False, 42, "private", True)
        forum_caps = resolve_chat_capabilities(forum)
        private_caps = resolve_chat_capabilities(private)
        self.assertTrue(forum_caps.supports_member_moderation)
        self.assertTrue(forum_caps.supports_topics)
        self.assertFalse(private_caps.supports_member_moderation)
        self.assertTrue(private_caps.supports_private_chat_topics)

    def test_readiness_summary(self):
        class C:
            def __init__(self, ok): self.ok = ok
            def as_dict(self): return {"ok": self.ok}
        self.assertTrue(readiness_summary([C(True), C(True)])["ready"])
        self.assertFalse(readiness_summary([C(True), C(False)])["ready"])

    def test_phase20_docs_and_commands_present(self):
        root = Path(__file__).resolve().parents[1]
        readme = (root / "README.md").read_text()
        app = (root / "ghostea/app.py").read_text()
        self.assertIn("Phase 20", readme)
        self.assertIn('"compatibility"', app)
        self.assertIn('"readiness"', app)


if __name__ == "__main__":
    unittest.main()
