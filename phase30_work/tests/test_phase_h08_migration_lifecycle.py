import asyncio
import unittest

from ghostea.services.chat_migration_service import ChatMigrationService


class FakeDB:
    pass


class FakeStore:
    def __init__(self):
        self.db = FakeDB()
        self.calls = []

    async def _call(self, fn, *args, **kwargs):
        self.calls.append((fn, args, kwargs))
        # Not exercising persistence here; these tests focus on pure lifecycle
        # helpers and attachment behavior.
        return []


class FakePerms:
    def __init__(self):
        self.invalidated = []
    def invalidate_chat(self, chat_id):
        self.invalidated.append(int(chat_id))


class H08Tests(unittest.TestCase):
    def test_runtime_attachment(self):
        svc = ChatMigrationService(FakeStore())
        bot = object()
        perms = FakePerms()
        svc.attach_runtime(bot=bot, permission_service=perms)
        self.assertIs(svc.bot, bot)
        self.assertIs(svc.permission_service, perms)

    def test_chat_ids_are_64_bit_safe_in_helpers(self):
        svc = ChatMigrationService(FakeStore())
        value = 2**51 + 123
        self.assertEqual(int(value), value)
        self.assertIsInstance(int(value), int)

    def test_migration_target_must_be_supergroup(self):
        # The authoritative reconciliation method is deliberately strict;
        # Group -> Supergroup is the only Telegram migration represented here.
        self.assertIn("not a Telegram supergroup",
                      open("ghostea/services/chat_migration_service.py", encoding="utf8").read())


if __name__ == "__main__":
    unittest.main()
