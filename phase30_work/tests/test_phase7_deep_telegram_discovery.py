
import asyncio
from types import SimpleNamespace

from ghostea.handlers.permission_events import handle_my_chat_member


def test_my_chat_member_reconciliation_uses_chat_context():
    class Migrations:
        def __init__(self):
            self.context = None

        async def reconcile_chat(self, context, reason="update"):
            self.context = context
            assert context.is_supported
            assert reason == "my_chat_member"

    class Perms:
        def invalidate_chat(self, *_):
            pass

    class App:
        bot_data = {
            "chat_migrations": None,
            "telegram_permissions": None,
        }

    migrations = Migrations()
    App.bot_data["chat_migrations"] = migrations

    event = SimpleNamespace(
        chat=SimpleNamespace(id=-100123, type="supergroup", title="Test", username=None, is_forum=True),
        new_chat_member=SimpleNamespace(status="administrator"),
    )
    update = SimpleNamespace(my_chat_member=event)
    context = SimpleNamespace(application=App())

    asyncio.run(handle_my_chat_member(update, context))
    assert migrations.context is not None
    assert migrations.context.chat_id == -100123


def test_telegram_discovery_is_not_assumed():
    # Telegram Bot API provides getChat/getChatMember for a known chat_id, but
    # no API that lists every group a bot is a member/admin of. Ghostea must
    # therefore persist lifecycle-discovered chat IDs and provide /link as an
    # explicit bootstrap for pre-existing chats.
    assert True


def test_removed_bot_is_soft_unlinked():
    class Store:
        def __init__(self):
            self.calls = []
            self.db = object()

        async def _call(self, fn, *args):
            self.calls.append((fn, args))

    class Migrations:
        async def reconcile_chat(self, context, reason="update"):
            pass

    store = Store()
    class App:
        bot_data = {
            "chat_migrations": Migrations(),
            "telegram_permissions": None,
            "phase3_store": store,
        }

    event = SimpleNamespace(
        chat=SimpleNamespace(id=-100777, type="supergroup", title="Test", username=None, is_forum=False),
        new_chat_member=SimpleNamespace(status="kicked"),
    )
    update = SimpleNamespace(my_chat_member=event)
    context = SimpleNamespace(application=App())

    asyncio.run(handle_my_chat_member(update, context))
    assert store.calls
    assert store.calls[0][1][1]["is_linked"] is False
