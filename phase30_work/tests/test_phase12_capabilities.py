import unittest
from dataclasses import replace

from ghostea.services.chat_context import build_chat_context
from ghostea.services.chat_capabilities import (
    resolve_chat_capabilities,
    capabilities_from_registry,
)


class FakeChat:
    def __init__(self, chat_id, chat_type, username=None, is_forum=False):
        self.id = chat_id
        self.type = chat_type
        self.title = "Test"
        self.username = username
        self.is_forum = is_forum


class FakeMessage:
    def __init__(self, thread=None):
        self.message_thread_id = thread


class Phase12CapabilityTests(unittest.TestCase):
    def test_private_group(self):
        c = build_chat_context(FakeChat(-1, "group"))
        caps = resolve_chat_capabilities(c)
        self.assertEqual(caps.kind, "group")
        self.assertTrue(caps.is_private)
        self.assertFalse(caps.supports_topics)
        self.assertTrue(caps.supports_member_moderation)

    def test_public_group_is_supported_defensively(self):
        # A username can be present in synthetic/legacy data; capability
        # resolution must still treat the chat as a basic group.
        c = build_chat_context(FakeChat(-2, "group", username="legacy"))
        caps = resolve_chat_capabilities(c)
        self.assertEqual(caps.kind, "group")
        self.assertTrue(caps.is_public)
        self.assertFalse(caps.supports_topics)

    def test_private_normal_supergroup(self):
        c = build_chat_context(FakeChat(-3, "supergroup"))
        caps = resolve_chat_capabilities(c)
        self.assertEqual(caps.kind, "supergroup")
        self.assertFalse(caps.supports_topics)
        self.assertTrue(caps.supports_public_username)

    def test_public_forum_supergroup_topic(self):
        c = build_chat_context(
            FakeChat(-4, "supergroup", username="forum", is_forum=True),
            FakeMessage(77),
        )
        caps = resolve_chat_capabilities(c)
        self.assertEqual(caps.kind, "forum_supergroup")
        self.assertTrue(caps.is_public)
        self.assertTrue(caps.supports_topics)
        self.assertTrue(caps.is_topic_message)
        self.assertTrue(caps.allows_feature("topic_management"))
        self.assertEqual(caps.scope_kind, "topic")

    def test_forum_supergroup_without_thread_is_chat_scope(self):
        c = build_chat_context(FakeChat(-5, "supergroup", is_forum=True))
        caps = resolve_chat_capabilities(c)
        self.assertTrue(caps.is_forum)
        self.assertTrue(caps.supports_topics)
        self.assertFalse(caps.is_topic_message)
        self.assertEqual(caps.scope_kind, "chat")

    def test_registry_resolution(self):
        caps = capabilities_from_registry({
            "chat_id": -6,
            "chat_type": "supergroup",
            "visibility": "private",
            "is_forum": True,
        })
        self.assertEqual(caps.kind, "forum_supergroup")
        self.assertTrue(caps.is_private)

    def test_invalid_registry_forum_group_is_not_forum(self):
        caps = capabilities_from_registry({
            "chat_id": -7,
            "chat_type": "group",
            "visibility": "private",
            "is_forum": True,
        })
        self.assertEqual(caps.kind, "group")
        self.assertFalse(caps.supports_topics)

    def test_unknown_feature_is_rejected(self):
        c = build_chat_context(FakeChat(-8, "group"))
        with self.assertRaises(KeyError):
            c.capabilities.allows_feature("does_not_exist")


if __name__ == "__main__":
    unittest.main()
