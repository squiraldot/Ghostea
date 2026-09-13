from datetime import datetime, timedelta, timezone

from ghostea.services.telegram_service import muted_permissions, perform_ban_member, perform_mute_member
from ghostea.services.chat_context import build_chat_context
from ghostea.services.moderation_target_guard import verify_moderation_target


class Phase3ModerationService:
    SCOPE = "chat_wide_state_topic_aware_logs"

    def __init__(self, store, bot=None, permission_service=None):
        self.store = store
        self.bot = bot
        self.permission_service = permission_service

    async def issue_warning(self, chat, user, reason, source, topic_id=None):
        # Warning count and punishment ladder are intentionally chat-wide.
        # ``topic_id`` below is telemetry context only; it never scopes state.
        # Re-check the target immediately before recording/punishing so an
        # admin promotion or departure race fails closed.
        await verify_moderation_target(chat, user.id, self.permission_service)
        settings = await self.store.get_settings(chat.id)
        count = await self.store.add_warning(
            chat.id, user.id, reason, source
        )

        limit = max(1, int(settings.get("max_warnings", 3)))
        if count >= limit:
            result = await perform_ban_member(chat, user.id, self.permission_service)
            await self.store.log(
                chat.id, user.id, "BAN" if result.ok else "BAN_FAILED",
                reason,
                f"warning_count={count};action_status={result.status.value};detail={result.detail}",
                topic_id=topic_id,
            )
            return count, "ban" if result.ok else f"ban_failed:{result.status.value}"

        chat_context = build_chat_context(chat)
        # Basic groups support message deletion and member bans, but Telegram's
        # Bot API does not support per-member restrictions there. Keep the
        # warning ladder intact: warnings are recorded and the configured
        # warning limit still bans, while intermediate warnings remain
        # warning-only instead of attempting a guaranteed-to-fail mute.
        if not chat_context or not chat_context.capabilities.supports_member_restriction:
            await self.store.log(
                chat.id, user.id, "WARN", reason,
                f"warning_count={count};action=warning_only;basic_group_compat=true",
                topic_id=topic_id,
            )
            return count, "warn_only"

        minutes = (
            int(settings["mute1_minutes"])
            if count == 1
            else int(settings["mute2_minutes"])
        )
        result = await perform_mute_member(
            chat, user.id, minutes, self.permission_service
        )
        await self.store.log(
            chat.id, user.id, "MUTE" if result.ok else "MUTE_FAILED", reason,
            f"warning_count={count};minutes={minutes};action_status={result.status.value};detail={result.detail}",
            topic_id=topic_id,
        )
        return count, f"mute:{minutes}" if result.ok else f"mute_failed:{result.status.value}"
