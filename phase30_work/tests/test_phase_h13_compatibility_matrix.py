import unittest

from ghostea.services.compatibility_matrix import (
    H13_OPERATIONS,
    TELEGRAM_UPDATE_SHAPES,
    GHOSTEA_HANDLED_UPDATE_SHAPES,
    build_matrix,
    validate_matrix,
)
from ghostea.services.chat_context import ChatContext
from ghostea.services.chat_capabilities import resolve_chat_capabilities


class PhaseH13CompatibilityMatrixTests(unittest.TestCase):
    def setUp(self):
        self.matrix = build_matrix()
        self.by_name = {row["name"]: row for row in self.matrix}

    def test_matrix_is_self_consistent(self):
        self.assertEqual(validate_matrix(self.matrix), [])
        self.assertEqual(len(self.matrix), 9)
        self.assertTrue(H13_OPERATIONS)

    def test_basic_group_has_no_restriction_or_unban(self):
        row = self.by_name["basic_group_private"]
        self.assertTrue(row["supports_bans"])
        self.assertFalse(row["supports_restriction"])
        self.assertFalse(row["supports_unbans"])
        self.assertTrue(row["operations"]["ban_member"]["supported_by_ghostea"])
        self.assertFalse(row["operations"]["unban_member"]["supported_by_ghostea"])

    def test_supergroup_unban_is_supported(self):
        for name in ("supergroup_private", "supergroup_public", "forum_private", "forum_public"):
            self.assertTrue(self.by_name[name]["supports_unbans"])

    def test_private_topic_boundaries(self):
        off = self.by_name["private_chat_topics_disabled"]
        on = self.by_name["private_chat_topics_enabled"]
        self.assertFalse(off["supports_topics"])
        self.assertTrue(on["supports_topics"])
        self.assertTrue(on["operations"]["create_forum_topic"]["supported_by_ghostea"])
        self.assertTrue(on["operations"]["delete_forum_topic"]["supported_by_ghostea"])
        self.assertFalse(on["operations"]["close_forum_topic"]["supported_by_ghostea"])
        self.assertFalse(on["operations"]["reopen_forum_topic"]["supported_by_ghostea"])

    def test_direct_messages_fail_closed(self):
        row = self.by_name["channel_direct_messages"]
        self.assertFalse(row["supports_moderation"])
        self.assertFalse(row["supports_message_deletion"])
        self.assertFalse(row["supports_topics"])

        ctx = ChatContext(1, "supergroup", "", None, False, True, True, 42, "private", False, True)
        caps = resolve_chat_capabilities(ctx)
        self.assertFalse(caps.supports_member_moderation)
        self.assertFalse(caps.is_forum)

    def test_update_surface_includes_current_guest_and_lifecycle_updates(self):
        for value in ("guest_message", "managed_bot", "subscription", "stopped_message_generation", "message", "edited_message", "my_chat_member"):
            self.assertIn(value, TELEGRAM_UPDATE_SHAPES)
        self.assertTrue(GHOSTEA_HANDLED_UPDATE_SHAPES.issubset(TELEGRAM_UPDATE_SHAPES))

    def test_public_private_matrix_does_not_change_moderation_support(self):
        self.assertEqual(
            self.by_name["supergroup_private"]["supports_moderation"],
            self.by_name["supergroup_public"]["supports_moderation"],
        )
        self.assertEqual(
            self.by_name["forum_private"]["supports_topics"],
            self.by_name["forum_public"]["supports_topics"],
        )


if __name__ == "__main__":
    unittest.main()
