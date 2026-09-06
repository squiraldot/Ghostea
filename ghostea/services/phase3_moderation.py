from datetime import datetime, timedelta, timezone

from ghostea.services.telegram_service import muted_permissions
from ghostea.services.chat_context import build_chat_context


class Phase3ModerationService:
    SCOPE = "chat_wide_state_topic_aware_logs"

    def __init__(self, store):
        self.store = store

    async def issue_warning(self, chat, user, reason, source, topic_id=None):
        # Warning count and punishment ladder are intentionally chat-wide.
        # ``topic_id`` below is telemetry context only; it never scopes state.
        settings = await self.store.get_settings(chat.id)
        count = await self.store.add_warning(
            chat.id, user.id, reason, source
        )

        limit = max(1, int(settings.get("max_warnings", 3)))
        if count >= limit:
            await chat.ban_member(user_id=user.id)
            await self.store.log(
                chat.id, user.id, "BAN", reason,
                f"warning_count={count}",
                topic_id=topic_id,
            )
            return count, "ban"

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
        until_date = datetime.now(timezone.utc) + timedelta(minutes=minutes)

        await chat.restrict_member(
            user_id=user.id,
            permissions=muted_permissions(),
            until_date=until_date,
        )
        await self.store.log(
            chat.id, user.id, "MUTE", reason,
            f"warning_count={count};minutes={minutes}",
            topic_id=topic_id,
        )
        return count, f"mute:{minutes}"
