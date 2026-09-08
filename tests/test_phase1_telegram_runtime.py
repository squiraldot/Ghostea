import unittest

try:
    import telegram
    from telegram.constants import ChatMemberStatus, UpdateType
    from telegram.ext import ChatMemberHandler
except ImportError:  # pragma: no cover - dependency is installed in deployment
    telegram = None


@unittest.skipUnless(telegram is not None, "python-telegram-bot is not installed")
class TelegramRuntimeContractTests(unittest.TestCase):
    def test_pinned_ptb_runtime(self):
        self.assertEqual(telegram.__version__, "22.8")

    def test_chat_member_update_constants_exist(self):
        self.assertEqual(UpdateType.MY_CHAT_MEMBER, "my_chat_member")
        self.assertEqual(UpdateType.CHAT_MEMBER, "chat_member")
        self.assertNotEqual(ChatMemberHandler.MY_CHAT_MEMBER, ChatMemberHandler.CHAT_MEMBER)

    def test_owner_status_contract(self):
        self.assertEqual(ChatMemberStatus.OWNER, "creator")
        self.assertEqual(ChatMemberStatus.ADMINISTRATOR, "administrator")


if __name__ == "__main__":
    unittest.main()
