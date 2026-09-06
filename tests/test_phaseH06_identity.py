import unittest
from ghostea.services.sender_identity import classify_sender, moderation_sender


class PhaseH06IdentityTests(unittest.TestCase):
    def test_normal_human_user_is_targetable(self):
        msg = type("M", (), {
            "from_user": type("U", (), {"id": 7, "is_bot": False})(),
            "sender_chat": None,
        })()
        identity = classify_sender(msg)
        self.assertEqual(identity.kind, "user")
        self.assertEqual(identity.user_id, 7)
        self.assertIs(moderation_sender(msg), msg.from_user)

    def test_bot_sender_is_not_moderation_target(self):
        msg = type("M", (), {
            "from_user": type("U", (), {"id": 8, "is_bot": True})(),
            "sender_chat": None,
        })()
        self.assertFalse(classify_sender(msg).can_be_moderation_target)
        self.assertIsNone(moderation_sender(msg))

    def test_sender_chat_is_never_converted_to_user(self):
        msg = type("M", (), {
            "from_user": type("U", (), {"id": 9, "is_bot": False})(),
            "sender_chat": type("C", (), {"id": -100})(),
        })()
        identity = classify_sender(msg)
        self.assertTrue(identity.is_chat_sender)
        self.assertIsNone(identity.user_id)
        self.assertIsNone(moderation_sender(msg))

    def test_missing_identity_is_unknown(self):
        msg = type("M", (), {"from_user": None, "sender_chat": None})()
        identity = classify_sender(msg)
        self.assertTrue(identity.is_anonymous_or_unknown)
        self.assertFalse(identity.can_be_moderation_target)


if __name__ == "__main__":
    unittest.main()
