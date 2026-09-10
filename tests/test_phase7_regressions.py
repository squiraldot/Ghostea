import asyncio
import types
from unittest.mock import AsyncMock

import pytest

from ghostea.handlers.permission_events import handle_my_chat_member
from ghostea.services.group_authorization import GroupAuthorizationService


@pytest.mark.asyncio
async def test_my_chat_member_reconciles_a_chat_context_and_links_chat():
    class Chat:
        id = -100123
        type = "supergroup"
        title = "Test"
        username = None
        is_forum = True

    class Event:
        chat = Chat()
        new_chat_member = types.SimpleNamespace(status="administrator")

    class Migration:
        def __init__(self): self.context = None
        async def reconcile_chat(self, context, reason=None):
            self.context = context
            assert context.chat_id == -100123
            assert context.is_supported is True
            assert context.is_forum is True
            assert reason == "my_chat_member"

    class Perms:
        def invalidate_chat(self, chat_id): pass

    class App:
        bot_data = {"telegram_permissions": Perms(), "chat_migrations": Migration()}

    await handle_my_chat_member(types.SimpleNamespace(my_chat_member=Event()), types.SimpleNamespace(application=App()))
    assert App.bot_data["chat_migrations"].context is not None


@pytest.mark.asyncio
async def test_authorization_uses_live_bot_and_user_status_after_registry_link():
    class Store:
        async def list_registered_chats(self, limit=500):
            return [{"chat_id": -1001, "chat_type": "supergroup", "title": "Forum", "is_forum": True}]

    class Chat:
        def __init__(self, chat_id): self.id = chat_id

    class Bot:
        async def get_chat(self, chat_id): return Chat(chat_id)

    class Perms:
        bot = Bot()
        class Policy:
            async def call_read(self, fn, *args, **kwargs): return await fn(*args)
        error_policy = Policy()
        async def bot_permissions(self, chat, force=False): return types.SimpleNamespace(is_admin=True)
        async def member(self, chat, user_id, force=False): return types.SimpleNamespace(status="administrator")

    result = await GroupAuthorizationService(Store(), Perms()).list_authorized_groups(77)
    assert [x.chat_id for x in result] == [-1001]
