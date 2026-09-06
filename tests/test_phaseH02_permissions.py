import asyncio
import unittest
from unittest.mock import AsyncMock

try:
    import telegram  # noqa: F401
except ModuleNotFoundError:
    telegram = None

if telegram is None:
    class PhaseH02PermissionTests(unittest.TestCase):
        @unittest.skip("python-telegram-bot is not installed in the test runtime")
        def test_h02_dependency(self):
            pass
else:

    from ghostea.services.permission_service import (
        PermissionLookupError, TelegramPermissionService
    )
    from ghostea.services.telegram_service import (
        invalidate_admin_cache, is_admin, unmute_member, UnsupportedChatFeature
    )
    from ghostea.services.chat_capabilities import BotPermissions
    
    
    @unittest.skipIf(telegram is None, "python-telegram-bot is not installed in the test runtime")
    class PhaseH02PermissionTests(unittest.TestCase):
        def test_bot_permission_cache_and_invalidation(self):
            async def run():
                class Bot:
                    async def get_me(self):
                        return type("U", (), {"id": 99})()
                chat = AsyncMock()
                chat.id = -100
                member = type("M", (), {
                    "status": "administrator",
                    "can_delete_messages": True,
                    "can_restrict_members": True,
                    "can_manage_topics": True,
                    "can_invite_users": True,
                    "can_change_info": True,
                })()
                chat.get_member = AsyncMock(return_value=member)
                svc = TelegramPermissionService(Bot(), bot_ttl=60, member_ttl=30)
                first = await svc.bot_permissions(chat)
                second = await svc.bot_permissions(chat)
                self.assertTrue(first.can_delete_messages)
                self.assertIs(first, second)
                self.assertEqual(chat.get_member.await_count, 1)
                svc.invalidate_chat(chat.id)
                await svc.bot_permissions(chat)
                self.assertEqual(chat.get_member.await_count, 2)
            asyncio.run(run())
    
        def test_bot_lookup_failure_is_unknown_and_fail_closed(self):
            async def run():
                class Bot:
                    async def get_me(self):
                        return type("U", (), {"id": 99})()
                chat = AsyncMock()
                chat.id = -100
                chat.get_member = AsyncMock(side_effect=RuntimeError("timeout"))
                svc = TelegramPermissionService(Bot())
                with self.assertRaises(PermissionLookupError):
                    await svc.bot_permissions(chat)
                with self.assertRaises(PermissionLookupError):
                    await svc.require_bot(chat, "ban_member")
            asyncio.run(run())
    
        def test_admin_cache_invalidation(self):
            async def run():
                chat = AsyncMock()
                chat.id = -100
                admin = type("M", (), {"status": "administrator"})()
                chat.get_member = AsyncMock(return_value=admin)
                invalidate_admin_cache(chat.id)
                self.assertTrue(await is_admin(chat, 7))
                self.assertTrue(await is_admin(chat, 7))
                self.assertEqual(chat.get_member.await_count, 1)
                invalidate_admin_cache(chat.id, 7)
                self.assertTrue(await is_admin(chat, 7))
                self.assertEqual(chat.get_member.await_count, 2)
            asyncio.run(run())
    
        def test_unmute_never_uses_synthetic_permissions_after_get_chat_failure(self):
            async def run():
                chat = AsyncMock()
                chat.id = -100
                chat.type = "supergroup"
                chat.get_chat = AsyncMock(side_effect=RuntimeError("timeout"))
                with self.assertRaises(PermissionLookupError):
                    await unmute_member(chat, 7)
                chat.restrict_member.assert_not_awaited()
            asyncio.run(run())
    
    
    if __name__ == "__main__":
        unittest.main()
