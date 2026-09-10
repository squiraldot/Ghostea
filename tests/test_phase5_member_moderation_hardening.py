import unittest
from unittest.mock import AsyncMock

try:
    from telegram.constants import ChatMemberStatus
    from ghostea.services.moderation_target_guard import verify_moderation_target, ModerationTargetError
    TELEGRAM_OK = True
except ModuleNotFoundError:
    TELEGRAM_OK = False


@unittest.skipUnless(TELEGRAM_OK, "python-telegram-bot is not installed in the test runtime")
class Phase5TargetGuardTests(unittest.IsolatedAsyncioTestCase):
    class User:
        def __init__(self, user_id, is_bot=False):
            self.id = user_id
            self.is_bot = is_bot

    class Member:
        def __init__(self, status, user):
            self.status = status
            self.user = user

    class Chat:
        id = -100123

        def __init__(self, member):
            self.member = member
            self.get_member = AsyncMock(return_value=member)

    class Permissions:
        def __init__(self, member):
            self.member_value = member
            self.member_calls = []

        async def member(self, chat, user_id, force=False):
            self.member_calls.append((chat.id, user_id, force))
            return self.member_value

    async def test_live_target_uses_forced_lookup(self):
        member = self.Member(ChatMemberStatus.MEMBER, self.User(7))
        perms = self.Permissions(member)
        target = await verify_moderation_target(self.Chat(member), 7, perms)
        self.assertEqual(target.user_id, 7)
        self.assertEqual(perms.member_calls[-1], (-100123, 7, True))

    async def test_admin_target_is_rejected(self):
        member = self.Member(ChatMemberStatus.ADMINISTRATOR, self.User(7))
        with self.assertRaises(ModerationTargetError):
            await verify_moderation_target(self.Chat(member), 7, self.Permissions(member))

    async def test_owner_target_is_rejected(self):
        member = self.Member(ChatMemberStatus.OWNER, self.User(7))
        with self.assertRaises(ModerationTargetError):
            await verify_moderation_target(self.Chat(member), 7, self.Permissions(member))

    async def test_bot_target_is_rejected(self):
        member = self.Member(ChatMemberStatus.MEMBER, self.User(7, is_bot=True))
        with self.assertRaises(ModerationTargetError):
            await verify_moderation_target(self.Chat(member), 7, self.Permissions(member))

    async def test_self_target_is_rejected_before_api_call(self):
        member = self.Member(ChatMemberStatus.MEMBER, self.User(7))
        perms = self.Permissions(member)
        with self.assertRaises(ModerationTargetError):
            await verify_moderation_target(self.Chat(member), 7, perms, requester_id=7)
        self.assertEqual(perms.member_calls, [])

    async def test_departed_target_is_rejected(self):
        member = self.Member(ChatMemberStatus.LEFT, self.User(7))
        with self.assertRaises(ModerationTargetError):
            await verify_moderation_target(self.Chat(member), 7, self.Permissions(member))


if __name__ == "__main__":
    unittest.main()
