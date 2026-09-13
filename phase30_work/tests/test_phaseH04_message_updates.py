import unittest
from types import SimpleNamespace

from ghostea.services.message_content import (
    extract_message_content,
    is_command_message,
    message_update_kind,
)


class MessageUpdateCoverageTests(unittest.TestCase):
    def test_normal_message_update(self):
        update = SimpleNamespace(message=SimpleNamespace(), edited_message=None)
        self.assertEqual(message_update_kind(update), "message")

    def test_edited_message_update(self):
        update = SimpleNamespace(message=None, edited_message=SimpleNamespace())
        self.assertEqual(message_update_kind(update), "edited_message")

    def test_text_content(self):
        message = SimpleNamespace(text="hello", caption=None)
        self.assertEqual(extract_message_content(message), ("hello", "text"))

    def test_caption_content(self):
        message = SimpleNamespace(text=None, caption="caption")
        self.assertEqual(extract_message_content(message), ("caption", "caption"))

    def test_non_text_media_is_not_fed_to_engine(self):
        message = SimpleNamespace(text=None, caption=None, photo=[object()])
        text, kind = extract_message_content(message)
        self.assertEqual(text, "")
        self.assertTrue(kind.startswith("service_or_"))

    def test_bot_command_detection(self):
        entity = SimpleNamespace(type="bot_command")
        message = SimpleNamespace(entities=[entity], caption_entities=None)
        self.assertTrue(is_command_message(message))

    def test_caption_bot_command_detection(self):
        entity = SimpleNamespace(type="bot_command")
        message = SimpleNamespace(entities=None, caption_entities=[entity])
        self.assertTrue(is_command_message(message))

    def test_non_command_content(self):
        message = SimpleNamespace(entities=None, caption_entities=None)
        self.assertFalse(is_command_message(message))


if __name__ == "__main__":
    unittest.main()
