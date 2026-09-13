import unittest

from ghostea.services.chat_context import build_chat_context
from ghostea.services.chat_capabilities import (
    resolve_chat_capabilities,
    resolve_supergroup_compatibility,
)


class FakeChat:
    def __init__(self, chat_id, chat_type="supergroup", username=None, is_forum=False):
        self.id = chat_id
        self.type = chat_type
        self.title = "Supergroup Test"
        self.username = username
        self.is_forum = is_forum


class Phase14SupergroupTests(unittest.TestCase):
    def test_normal_supergroup_has_full_member_moderation(self):
        context = build_chat_context(FakeChat(-200, "supergroup"))
        caps = resolve_chat_capabilities(context)
        profile = resolve_supergroup_compatibility(caps)

        self.assertTrue(caps.is_supergroup)
        self.assertFalse(caps.is_forum)
        self.assertTrue(profile.is_fully_moderatable)
        self.assertTrue(profile.supports_individual_restrictions)
        self.assertTrue(profile.supports_bans)
        self.assertTrue(profile.supports_default_permissions)
        self.assertTrue(profile.supports_message_deletion)
        self.assertFalse(profile.supports_topics)

    def test_public_supergroup_supports_public_identity(self):
        context = build_chat_context(
            FakeChat(-201, "supergroup", username="ghostea_public")
        )
        caps = resolve_chat_capabilities(context)
        profile = resolve_supergroup_compatibility(caps)

        self.assertTrue(caps.is_public)
        self.assertTrue(profile.supports_public_username)

    def test_normal_supergroup_is_not_forum(self):
        context = build_chat_context(FakeChat(-202, "supergroup", is_forum=False))
        caps = resolve_chat_capabilities(context)

        self.assertFalse(caps.is_forum)
        self.assertFalse(caps.supports_topics)
        self.assertFalse(caps.supports_topic_management)
        self.assertFalse(caps.supports_forum_topic_messages)

    def test_forum_is_excluded_from_phase14_profile(self):
        context = build_chat_context(FakeChat(-203, "supergroup", is_forum=True))
        caps = resolve_chat_capabilities(context)
        profile = resolve_supergroup_compatibility(caps)

        self.assertTrue(caps.is_forum)
        self.assertFalse(profile.is_fully_moderatable)
        self.assertFalse(profile.supports_topics)

    def test_unsupported_context_has_no_supergroup_profile(self):
        profile = resolve_supergroup_compatibility(None)
        self.assertFalse(profile.is_fully_moderatable)
        self.assertFalse(profile.supports_individual_restrictions)


if __name__ == "__main__":
    unittest.main()
