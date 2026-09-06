import unittest

from ghostea.services.chat_context import ChatContext
from ghostea.services.scope_policy import (
    CHAT_WIDE, FORUM_ONLY, TOPIC_AWARE, get_service_scope, scope_key,
)


def ctx(chat_id, chat_type="supergroup", forum=False, topic_id=None):
    return ChatContext(
        chat_id=chat_id,
        chat_type=chat_type,
        title="test",
        username=None,
        is_group=chat_type == "group",
        is_supergroup=chat_type == "supergroup",
        is_forum=forum,
        topic_id=topic_id,
    )


class Phase7ScopeTests(unittest.TestCase):
    def test_normal_group_never_gets_topic_scope(self):
        c = ctx(10, "group", False, 77)
        self.assertEqual(c.scope_key, (10, None))
        self.assertEqual(c.chat_scope_key, (10, None))
        self.assertIsNone(scope_key(c, FORUM_ONLY))

    def test_forum_topic_scope_is_chat_plus_topic(self):
        c = ctx(-100, "supergroup", True, 77)
        self.assertEqual(c.scope_key, (-100, 77))
        self.assertEqual(c.chat_scope_key, (-100, None))
        self.assertEqual(c.service_scope_key("flood"), (-100, 77))
        self.assertEqual(c.service_scope_key("warnings"), (-100, None))

    def test_non_forum_supergroup_is_chat_scoped(self):
        c = ctx(-101, "supergroup", False, None)
        self.assertEqual(c.scope_key, (-101, None))
        self.assertEqual(c.service_scope_key("moderation_logs"), (-101, None))

    def test_service_registry_is_explicit(self):
        self.assertEqual(get_service_scope("anti_raid").mode, CHAT_WIDE)
        self.assertEqual(get_service_scope("moderation").mode, TOPIC_AWARE)


if __name__ == "__main__":
    unittest.main()
