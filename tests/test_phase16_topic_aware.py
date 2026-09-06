import unittest
from unittest.mock import AsyncMock

from ghostea.services.topic_messaging import send_in_context


class FakeChat:
    def __init__(self, is_forum=True):
        self.is_forum = is_forum
        self.send_message = AsyncMock(return_value=True)


class Phase16TopicAwareTests(unittest.IsolatedAsyncioTestCase):
    async def test_forum_topic_notice_targets_originating_topic(self):
        chat = FakeChat(True)
        await send_in_context(chat, "notice", topic_id=42)
        chat.send_message.assert_awaited_once_with(
            "notice", message_thread_id=42
        )

    async def test_general_topic_uses_default_destination(self):
        chat = FakeChat(True)
        await send_in_context(chat, "notice", topic_id=1)
        chat.send_message.assert_awaited_once_with("notice")

    async def test_non_forum_never_receives_thread_argument(self):
        chat = FakeChat(False)
        await send_in_context(chat, "notice", topic_id=42)
        chat.send_message.assert_awaited_once_with("notice")


if __name__ == "__main__":
    unittest.main()
