import unittest

from ghostea.services.chat_context import ChatContext, build_chat_context


class FakeChat:
    def __init__(self, chat_id, chat_type, username=None, is_forum=False):
        self.id = chat_id
        self.type = chat_type
        self.username = username
        self.is_forum = is_forum
        self.title = "Test"


class FakeMessage:
    def __init__(self, thread_id=None):
        self.message_thread_id = thread_id


class Phase11ChatIdentityTests(unittest.TestCase):
    def test_private_basic_group(self):
        c = build_chat_context(FakeChat(-1, "group"))
        self.assertEqual(c.visibility, "private")
        self.assertTrue(c.is_private)
        self.assertFalse(c.is_public)
        self.assertFalse(c.is_forum)
        self.assertIsNone(c.topic_id)

    def test_basic_group_with_username_is_not_forced_into_forum(self):
        # Defensive invariant: is_forum is only valid for supergroups.
        c = build_chat_context(FakeChat(-2, "group", username="legacyname", is_forum=True))
        self.assertEqual(c.visibility, "public")
        self.assertFalse(c.is_forum)
        self.assertIsNone(c.topic_id)

    def test_private_normal_supergroup(self):
        c = build_chat_context(FakeChat(-100, "supergroup"))
        self.assertEqual(c.visibility, "private")
        self.assertFalse(c.is_forum)
        self.assertIsNone(c.topic_id)

    def test_public_normal_supergroup(self):
        c = build_chat_context(FakeChat(-101, "supergroup", username="publicgroup"))
        self.assertEqual(c.visibility, "public")
        self.assertTrue(c.is_public)
        self.assertFalse(c.is_forum)

    def test_private_forum_supergroup_topic(self):
        c = build_chat_context(
            FakeChat(-102, "supergroup", is_forum=True),
            FakeMessage(77),
        )
        self.assertEqual(c.visibility, "private")
        self.assertTrue(c.is_forum)
        self.assertTrue(c.is_topic_capable)
        self.assertTrue(c.is_topic_message)
        self.assertEqual(c.topic_id, 77)

    def test_public_forum_supergroup_topic(self):
        c = build_chat_context(
            FakeChat(-103, "supergroup", username="forumgroup", is_forum=True),
            FakeMessage(88),
        )
        self.assertEqual(c.visibility, "public")
        self.assertTrue(c.is_public)
        self.assertTrue(c.is_forum)
        self.assertEqual(c.topic_id, 88)

    def test_backward_compatible_direct_context_constructor(self):
        c = ChatContext(-5, "group", "Test", None, True, False, False, None)
        self.assertEqual(c.visibility, "private")


if __name__ == "__main__":
    unittest.main()
