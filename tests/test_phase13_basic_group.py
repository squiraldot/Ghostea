import unittest

from ghostea.services.chat_context import build_chat_context
from ghostea.services.chat_capabilities import resolve_chat_capabilities


class FakeChat:
    def __init__(self, chat_id, chat_type="group", username=None, is_forum=False):
        self.id = chat_id
        self.type = chat_type
        self.title = "Basic Test"
        self.username = username
        self.is_forum = is_forum


class Phase13BasicGroupTests(unittest.TestCase):
    def test_basic_group_capability_matrix(self):
        context = build_chat_context(FakeChat(-100, "group"))
        caps = resolve_chat_capabilities(context)

        self.assertEqual(caps.kind, "group")
        self.assertTrue(caps.is_private)
        self.assertTrue(caps.supports_member_moderation)
        self.assertTrue(caps.supports_message_deletion)
        self.assertTrue(caps.supports_member_ban)
        self.assertFalse(caps.supports_member_restriction)
        self.assertTrue(caps.supports_default_permissions)
        self.assertTrue(caps.supports_group_settings)
        self.assertFalse(caps.supports_topics)
        self.assertFalse(caps.supports_topic_management)

    def test_basic_group_never_gets_topic_scope(self):
        context = build_chat_context(
            FakeChat(-101, "group"),
            type("Message", (), {"message_thread_id": 999})(),
        )
        caps = resolve_chat_capabilities(context)

        self.assertIsNone(context.topic_id)
        self.assertFalse(caps.is_topic_message)
        self.assertEqual(caps.scope_kind, "chat")
        self.assertFalse(caps.supports_topics)

    def test_basic_group_public_legacy_metadata_is_defensive_only(self):
        context = build_chat_context(FakeChat(-102, "group", username="legacy"))
        caps = resolve_chat_capabilities(context)

        self.assertTrue(caps.is_public)
        self.assertFalse(caps.supports_topics)
        self.assertFalse(caps.supports_member_restriction)

    def test_supergroup_gains_individual_restriction(self):
        context = build_chat_context(FakeChat(-103, "supergroup"))
        caps = resolve_chat_capabilities(context)

        self.assertEqual(caps.kind, "supergroup")
        self.assertTrue(caps.supports_member_restriction)
        self.assertTrue(caps.supports_member_ban)

    def test_capability_dict_exposes_basic_group_boundaries(self):
        context = build_chat_context(FakeChat(-104, "group"))
        data = resolve_chat_capabilities(context).as_dict()

        self.assertFalse(data["supports_member_restriction"])
        self.assertTrue(data["supports_message_deletion"])
        self.assertTrue(data["supports_member_ban"])
        self.assertTrue(data["supports_default_permissions"])
        self.assertFalse(data["supports_topics"])


if __name__ == "__main__":
    unittest.main()
