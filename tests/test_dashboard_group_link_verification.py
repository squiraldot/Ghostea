import asyncio
import unittest
from types import SimpleNamespace

from ghostea.web_server import DashboardHandler


class FakePolicy:
    async def call_read(self, operation, *, scope_id=None):
        return await operation()


class FakeBot:
    def __init__(self, member):
        self.member = member
        self.get_chat_calls = []
        self.get_member_calls = []
        self.get_admin_calls = []

    async def get_chat(self, chat_id):
        self.get_chat_calls.append(chat_id)
        return SimpleNamespace(id=chat_id, type="supergroup", title="Test", username=None, is_forum=False)

    async def get_me(self):
        return SimpleNamespace(id=777)

    async def get_chat_member(self, chat_id, user_id):
        self.get_member_calls.append((chat_id, user_id))
        if isinstance(self.member, Exception):
            raise self.member
        return self.member

    async def get_chat_administrators(self, chat_id):
        self.get_admin_calls.append(chat_id)
        return self.member


class FakeStore:
    def __init__(self):
        self.linked = None
    async def link_chat(self, chat, linked_by=None):
        self.linked = (chat.id, linked_by)

    async def get_settings(self, chat_id):
        return {}


class LinkVerificationTests(unittest.TestCase):
    def make_handler(self, bot):
        h = object.__new__(DashboardHandler)
        h.permission_service = SimpleNamespace(error_policy=FakePolicy())
        h.store = FakeStore()
        h.server = SimpleNamespace(bot=bot)
        return h

    def test_negative_supergroup_id_links_when_bot_is_admin(self):
        bot = FakeBot(SimpleNamespace(status="administrator"))
        h = self.make_handler(bot)
        result = h._verify_and_link_group(-1004382037144, "1")
        self.assertTrue(result["ok"])
        self.assertEqual(bot.get_chat_calls, [-1004382037144])
        self.assertEqual(bot.get_member_calls, [(-1004382037144, 777)])
        self.assertEqual(h.store.linked, (-1004382037144, "1"))

    def test_non_admin_is_rejected_as_bot_not_admin(self):
        bot = FakeBot(SimpleNamespace(status="member"))
        h = self.make_handler(bot)
        with self.assertRaisesRegex(PermissionError, "bot_not_admin"):
            h._verify_and_link_group(-1004382037144, "1")
        self.assertIsNone(h.store.linked)

    def test_member_lookup_failure_falls_back_to_admin_list(self):
        bot = FakeBot([SimpleNamespace(user=SimpleNamespace(id=777), status="administrator")])
        bot.member = RuntimeError("member lookup unavailable")
        # Fallback must return the admin-list entries.
        bot.get_chat_administrators = lambda chat_id: asyncio.sleep(0, result=[SimpleNamespace(user=SimpleNamespace(id=777), status="administrator")])
        h = self.make_handler(bot)
        result = h._verify_and_link_group(-1004382037144, "1")
        self.assertTrue(result["ok"])
        self.assertEqual(h.store.linked, (-1004382037144, "1"))


if __name__ == "__main__":
    unittest.main()
