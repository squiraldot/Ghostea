import unittest

from ghostea.services.telegram_contract import (
    ADMIN_PERMISSION_FIELDS,
    CHAT_PERMISSION_FIELDS,
    GHOSTEA_MODERATION_CHAT_TYPES,
    TELEGRAM_BOT_API_BASELINE,
    TELEGRAM_CONTRACT,
    validate_chat_type,
    validate_permission_mapping,
    validate_update_type,
)


class PhaseH01TelegramContractTests(unittest.TestCase):
    def test_current_bot_api_baseline(self):
        self.assertEqual(TELEGRAM_BOT_API_BASELINE, "10.3")
        self.assertEqual(TELEGRAM_CONTRACT.ptb_major, 22)

    def test_chat_types_match_telegram_contract(self):
        for value in ("private", "group", "supergroup", "channel"):
            self.assertTrue(validate_chat_type(value))
        self.assertEqual(GHOSTEA_MODERATION_CHAT_TYPES, {"group", "supergroup"})
        self.assertFalse(validate_chat_type("forum"))

    def test_chat_permissions_are_explicit_and_current(self):
        expected = {
            "can_send_messages",
            "can_send_audios",
            "can_send_documents",
            "can_send_photos",
            "can_send_videos",
            "can_send_video_notes",
            "can_send_voice_notes",
            "can_send_polls",
            "can_send_other_messages",
            "can_add_web_page_previews",
            "can_react_to_messages",
            "can_edit_tag",
            "can_change_info",
            "can_invite_users",
            "can_pin_messages",
            "can_manage_topics",
        }
        self.assertEqual(set(CHAT_PERMISSION_FIELDS), expected)
        self.assertNotIn("can_manage_direct_messages", CHAT_PERMISSION_FIELDS)

    def test_admin_rights_keep_direct_messages_separate(self):
        self.assertIn("can_manage_direct_messages", ADMIN_PERMISSION_FIELDS)
        self.assertIn("can_manage_topics", ADMIN_PERMISSION_FIELDS)
        self.assertIn("can_restrict_members", ADMIN_PERMISSION_FIELDS)

    def test_update_contract_includes_lifecycle_updates(self):
        for value in (
            "message",
            "edited_message",
            "chat_member",
            "my_chat_member",
            "chat_join_request",
        ):
            self.assertTrue(validate_update_type(value))

    def test_operation_contract_has_correct_topic_delete_permission(self):
        contract = TELEGRAM_CONTRACT.operation("delete_forum_topic")
        self.assertEqual(contract["required_admin_right"], "can_delete_messages")
        self.assertIn("private", contract["chat_types"])

    def test_permission_mapping_rejects_unknown_fields(self):
        self.assertTrue(validate_permission_mapping({"can_manage_topics": True}))
        self.assertFalse(validate_permission_mapping({"can_fake_telegram_permission": True}))


if __name__ == "__main__":
    unittest.main()
