import unittest

from ghostea.services.chat_context import build_chat_context
from ghostea.services.chat_capabilities import resolve_chat_capabilities
from ghostea.services.chat_visibility import resolve_chat_visibility, visibility_from_registry


class FakeChat:
    def __init__(self, chat_id, chat_type="supergroup", username=None, is_forum=False):
        self.id = chat_id
        self.type = chat_type
        self.title = "Visibility Test"
        self.username = username
        self.is_forum = is_forum


class Phase17VisibilityTests(unittest.TestCase):
    def test_public_supergroup_gets_public_identity_and_url(self):
        ctx = build_chat_context(FakeChat(-301, "supergroup", "ghostea_public"))
        visibility = resolve_chat_visibility(ctx)
        self.assertTrue(visibility.is_public)
        self.assertEqual(visibility.username, "ghostea_public")
        self.assertEqual(visibility.public_url, "https://t.me/ghostea_public")
        self.assertTrue(visibility.can_show_public_link)

    def test_private_supergroup_has_no_public_url(self):
        ctx = build_chat_context(FakeChat(-302, "supergroup"))
        visibility = resolve_chat_visibility(ctx)
        self.assertTrue(visibility.is_private)
        self.assertIsNone(visibility.public_url)
        self.assertFalse(visibility.can_show_public_link)

    def test_basic_group_is_always_private(self):
        ctx = build_chat_context(FakeChat(-303, "group", "legacy_name"))
        visibility = resolve_chat_visibility(ctx)
        self.assertTrue(visibility.is_private)
        self.assertIsNone(visibility.username)
        self.assertIsNone(visibility.public_url)

        caps = resolve_chat_capabilities(ctx)
        self.assertFalse(caps.supports_public_username)

    def test_forum_public_supergroup_keeps_public_identity(self):
        ctx = build_chat_context(FakeChat(-304, "supergroup", "forum_name", True))
        visibility = resolve_chat_visibility(ctx)
        self.assertTrue(visibility.is_public)
        self.assertEqual(visibility.public_url, "https://t.me/forum_name")

    def test_registry_normalizes_stale_basic_group_public_metadata(self):
        v = visibility_from_registry({
            "chat_id": -305,
            "chat_type": "group",
            "username": "stale_public",
            "visibility": "public",
            "is_forum": False,
        })
        self.assertTrue(v.is_private)
        self.assertIsNone(v.public_url)

    def test_registry_public_supergroup_requires_username(self):
        v = visibility_from_registry({
            "chat_id": -306,
            "chat_type": "supergroup",
            "username": None,
            "visibility": "public",
            "is_forum": False,
        })
        self.assertTrue(v.is_private)
        self.assertIsNone(v.public_url)

    def test_visibility_does_not_disable_moderation(self):
        public_ctx = build_chat_context(FakeChat(-307, "supergroup", "public_name"))
        private_ctx = build_chat_context(FakeChat(-308, "supergroup"))
        self.assertTrue(resolve_chat_capabilities(public_ctx).supports_member_moderation)
        self.assertTrue(resolve_chat_capabilities(private_ctx).supports_member_moderation)


if __name__ == "__main__":
    unittest.main()
