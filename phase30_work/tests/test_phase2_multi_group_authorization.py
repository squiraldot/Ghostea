import pytest

from ghostea.services.group_authorization import GroupAuthorizationService
from ghostea.services.permission_service import PermissionLookupError


class Member:
    def __init__(self, status):
        self.status = status


class BotPermissions:
    def __init__(self, is_admin):
        self.is_admin = is_admin


class FakeStore:
    def __init__(self, rows):
        self.rows = rows

    async def list_registered_chats(self, limit=500):
        return self.rows[:limit]


class FakePermissionService:
    def __init__(self, bot_admin=None, user_status=None, failures=None):
        self.bot_admin = bot_admin or {}
        self.user_status = user_status or {}
        self.failures = failures or set()
        self.bot = object()
        self.error_policy = None

    async def bot_permissions(self, chat, force=False):
        chat_id = int(chat.id)
        if ("bot", chat_id) in self.failures:
            raise PermissionLookupError("bot_lookup_failed")
        return BotPermissions(self.bot_admin.get(chat_id, False))

    async def member(self, chat, user_id, force=False):
        chat_id = int(chat.id)
        key = (chat_id, int(user_id))
        if key in self.failures:
            raise PermissionLookupError("member_lookup_failed")
        return Member(self.user_status.get(key, "member"))


class Chat:
    def __init__(self, chat_id):
        self.id = chat_id


@pytest.mark.asyncio
async def test_only_groups_where_user_and_bot_are_admin_are_returned():
    rows = [
        {"chat_id": 1, "chat_type": "group", "title": "A", "is_forum": False},
        {"chat_id": 2, "chat_type": "supergroup", "title": "B", "is_forum": True},
        {"chat_id": 3, "chat_type": "supergroup", "title": "C", "is_forum": False},
    ]
    perms = FakePermissionService(
        bot_admin={1: True, 2: True, 3: False},
        user_status={(1, 99): "administrator", (2, 99): "creator", (3, 99): "administrator"},
    )

    # Inject get_chat behavior expected by the service.
    class Policy:
        async def call_read(self, fn, *args, **kwargs):
            return Chat(args[0])

    perms.error_policy = Policy()
    perms.bot = object()
    # service accesses bot.get_chat; provide it explicitly.
    class Bot:
        async def get_chat(self, chat_id):
            return Chat(chat_id)
    perms.bot = Bot()

    result = await GroupAuthorizationService(
        FakeStore(rows), perms
    ).list_authorized_groups(99)

    assert [x.chat_id for x in result] == [1, 2]
    assert result[1].is_forum is True


@pytest.mark.asyncio
async def test_non_admin_user_is_excluded_even_when_bot_is_admin():
    rows = [{"chat_id": 10, "chat_type": "supergroup", "title": "A", "is_forum": False}]
    perms = FakePermissionService(bot_admin={10: True}, user_status={(10, 99): "member"})

    class Policy:
        async def call_read(self, fn, *args, **kwargs):
            return Chat(args[0])

    class Bot:
        async def get_chat(self, chat_id):
            return Chat(chat_id)

    perms.error_policy = Policy()
    perms.bot = Bot()

    result = await GroupAuthorizationService(FakeStore(rows), perms).list_authorized_groups(99)
    assert result == []


@pytest.mark.asyncio
async def test_lookup_failure_fails_closed_for_one_group_without_blocking_others():
    rows = [
        {"chat_id": 10, "chat_type": "supergroup", "title": "Bad", "is_forum": False},
        {"chat_id": 11, "chat_type": "supergroup", "title": "Good", "is_forum": False},
    ]
    perms = FakePermissionService(
        bot_admin={10: True, 11: True},
        user_status={(10, 99): "administrator", (11, 99): "administrator"},
        failures={("bot", 10)},
    )

    class Policy:
        async def call_read(self, fn, *args, **kwargs):
            return await fn(*args)

    class Bot:
        async def get_chat(self, chat_id):
            return Chat(chat_id)

    perms.error_policy = Policy()
    perms.bot = Bot()

    result = await GroupAuthorizationService(FakeStore(rows), perms).list_authorized_groups(99)
    assert [x.chat_id for x in result] == [11]
