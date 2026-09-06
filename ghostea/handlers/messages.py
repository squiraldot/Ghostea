import logging

logger = logging.getLogger("Ghostea")

from telegram import Update
from telegram.ext import ContextTypes

from ghostea.services.telegram_service import is_admin, mute_member, require_message_delete_permission, perform_delete_message, perform_mute_member
from ghostea.services.chat_context import build_chat_context
from ghostea.services.chat_capabilities import resolve_chat_capabilities
from ghostea.services.moderation_engine import ModerationContext
from ghostea.utils import display_name
from ghostea.services.topic_messaging import send_in_context


from ghostea.services.sender_identity import classify_sender, moderation_sender
from ghostea.services.message_content import (
    extract_message_content, is_command_message, message_update_kind,
)

async def check_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    sender_identity = classify_sender(message) if message else None

    # H04: service updates can legitimately have no effective user. Resolve
    # chat migration/topic lifecycle first; only moderation requires a user.
    if not message or not chat:
        return

    # Telegram emits a service message when a basic group is migrated to a
    # supergroup. Move Ghostea's persistent state before processing anything
    # else under the new chat id.
    migrate_to = getattr(message, "migrate_to_chat_id", None)
    migrate_from = getattr(message, "migrate_from_chat_id", None)
    if migrate_to is not None or migrate_from is not None:
        old_chat_id = int(chat.id) if migrate_to is not None else int(migrate_from)
        new_chat_id = int(migrate_to) if migrate_to is not None else int(chat.id)
        migrations = context.application.bot_data.get("chat_migrations")
        protection = context.application.bot_data.get("protection")
        if migrations:
            try:
                result = await migrations.handle_migration(
                    old_chat_id, new_chat_id, reason="telegram_migration"
                )
                if protection:
                    protection.discard_chat(old_chat_id)
                security = context.application.bot_data.get("security")
                if security:
                    security.discard_chat(old_chat_id)
                store = context.application.bot_data.get("phase3_store")
                if store:
                    store.invalidate_chat_cache(old_chat_id, new_chat_id)
                logger.info(
                    "Chat migration handled and reconciled: %s -> %s result=%s",
                    old_chat_id, new_chat_id, result,
                )
            except Exception:
                # The journaled migration is durable and resumable. Do not
                # pretend the lifecycle transition is fully verified when the
                # authoritative Telegram refresh fails.
                logger.exception(
                    "Chat migration/reconciliation incomplete: %s -> %s",
                    old_chat_id, new_chat_id,
                )
        return

    update_kind = message_update_kind(update)
    # Edited commands are still commands, not user content to moderate.
    if update_kind == "edited_message" and is_command_message(message):
        return
    # H06: sender_chat represents a chat-backed sender (including anonymous
    # administrators). Never turn it into a human member identity. Preserve
    # topic/service bookkeeping, then stop before moderation.
    safe_user = moderation_sender(message)
    if safe_user is None:
        try:
            store = context.application.bot_data.get("phase3_store")
            if store:
                private_topics_enabled = bool(
                    context.application.bot_data.get("private_topics_enabled", False)
                )
                service_context = build_chat_context(
                    chat, message, private_topics_enabled=private_topics_enabled
                )
                if service_context and service_context.is_topic_message:
                    await store.touch_topic(service_context, message)
        except Exception:
            logger.exception("Service/topic update registry handling failed")
        return
    user = safe_user

    private_topics_enabled = bool(
        context.application.bot_data.get("private_topics_enabled", False)
    )
    chat_context = build_chat_context(
        chat, message, private_topics_enabled=private_topics_enabled
    )
    if not chat_context:
        return

    capabilities = resolve_chat_capabilities(chat_context)

    # Private-chat topics are a Phase 19 context feature, not a moderation
    # target. Persist observed topic lifecycle/messages, but never run the
    # group moderation engine against a direct chat.
    if chat_context.is_private_chat:
        if chat_context.is_topic_message:
            try:
                await context.application.bot_data["phase3_store"].touch_topic(
                    chat_context, message
                )
            except Exception:
                logger.exception("Private topic registry update failed")
        return

    if not capabilities.supports_member_moderation:
        return

    store = context.application.bot_data["phase3_store"]
    try:
        await store.touch_chat(chat_context)
    except Exception:
        logger.exception("Chat registry update failed")
        # Do not continue under an unknown persistence state. The dashboard
        # and moderation configuration rely on the same durable chat record.
        return

    # touch_chat() now also materializes default group settings. This happens
    # before the admin fast-path so administrator-only activity still makes
    # the group visible/configurable in the dashboard.

    # Phase 3: persist forum-topic metadata independently from moderation.
    # This runs before the text check so Telegram topic service messages
    # (created/edited/closed/reopened/deleted) are also captured.
    if chat_context.is_topic_message:
        try:
            await store.touch_topic(chat_context, message)
        except Exception:
            logger.exception("Topic registry update failed")

    text, content_kind = extract_message_content(message)
    if not text:
        return

    try:
        if await is_admin(chat, user.id):
            return
    except Exception:
        logger.exception("Admin check failed")
        return

    store = context.application.bot_data["phase3_store"]
    # Keep the known-user directory useful for ordinary active members too.
    await store.touch_user(chat.id, user.id)
    settings = await store.get_effective_settings(
        chat.id, chat_context.topic_id
    )
    protection = context.application.bot_data["protection"]
    moderation = context.application.bot_data["phase3_moderation"]
    engine = context.application.bot_data["moderation_engine"]

    # Phase 5: keep Telegram/chat identity out of the settings dictionary.
    # The engine receives a typed request context so every moderation path uses
    # the same group/topic scope while settings stay purely configuration.
    evaluation_settings = dict(settings)
    moderation_context = ModerationContext(
        chat_id=chat_context.chat_id,
        user_id=user.id,
        topic_id=chat_context.topic_id,
        chat_type=chat_context.chat_type,
        is_forum=capabilities.is_forum,
    )

    custom_words = await store.get_custom_filters(chat.id, "word")
    custom_domains = await store.get_custom_filters(chat.id, "domain")
    custom_patterns = await store.get_custom_filters(chat.id, "pattern")

    detection = engine.evaluate(
        text,
        evaluation_settings,
        custom_words,
        custom_domains,
        custom_patterns,
        moderation_context=moderation_context,
    )

    if detection:
        delete_result = await perform_delete_message(
            message, chat, context.application.bot_data.get("telegram_permissions")
        )
        if not delete_result.ok:
            logger.warning(
                "Moderated message delete did not succeed: category=%s status=%s detail=%s",
                detection.category, delete_result.status.value, delete_result.detail,
            )
            try:
                await store.log(
                    chat.id, user.id, "DELETE_FAILED", detection.reason,
                    f"category={detection.category};update_kind={update_kind};content_kind={content_kind};action_status={delete_result.status.value};detail={delete_result.detail}",
                    topic_id=chat_context.topic_id,
                )
            except Exception:
                logger.exception("Failed to persist delete failure")

        if detection.action == "warn":
            try:
                count, action = await moderation.issue_warning(
                    chat,
                    user,
                    detection.reason,
                    detection.source,
                    topic_id=chat_context.topic_id,
                )
                await announce(
                    chat, user, count, action, settings, detection.score,
                    topic_id=chat_context.topic_id,
                )
            except Exception:
                logger.exception(
                    "Automatic moderation failed: category=%s",
                    detection.category,
                )
        else:
            try:
                if detection.category == "blocked_link":
                    await send_in_context(
                        chat,
                        f"🔗 Blocked link removed from {display_name(user)}.",
                        topic_id=chat_context.topic_id,
                    )
            except Exception:
                logger.exception("Moderation notice failed")

            await store.log(
                chat.id,
                user.id,
                f"DELETE_{detection.category.upper()}",
                detection.reason,
                f"risk_score={detection.score};topic_id={chat_context.topic_id};update_kind={update_kind};content_kind={content_kind}",
                topic_id=chat_context.topic_id,
            )
        return

    # Flood is deliberately evaluated only after content moderation so a
    # single abusive/spam message cannot consume a flood action first.
    if settings.get("flood_protection_enabled", True):
        triggered = protection.register_message(
            chat.id,
            user.id,
            int(settings.get("flood_window_seconds", 8)),
            int(settings.get("flood_message_limit", 6)),
            scope_key=chat_context.service_scope_key("flood"),
        )
        if triggered:
            minutes = int(settings.get("flood_mute_minutes", 10))
            result = await perform_mute_member(
                chat, user.id, minutes,
                permission_service=context.application.bot_data.get("telegram_permissions"),
            )
            if result.ok:
                await send_in_context(
                    chat,
                    f"🚨 {display_name(user)}\n\n"
                    f"Flood detected.\nMuted for {minutes} minutes.",
                    topic_id=chat_context.topic_id,
                )
                await store.log(
                    chat.id, user.id, "FLOOD_MUTE", "Flood protection",
                    f"minutes={minutes};risk_score=40;action_status={result.status.value}",
                    topic_id=chat_context.topic_id,
                )
            else:
                await store.log(
                    chat.id, user.id, "FLOOD_MUTE_FAILED", "Flood protection",
                    f"minutes={minutes};action_status={result.status.value};detail={result.detail}",
                    topic_id=chat_context.topic_id,
                )


async def announce(chat, user, count, action, settings, risk_score=None, topic_id=None):
    name = display_name(user)
    limit = int(settings["max_warnings"])
    suffix = f"\nRisk score: {risk_score}" if risk_score is not None else ""

    try:
        if action == "ban":
            await send_in_context(
                chat,
                f"🚫 {name}\n\n"
                f"Warning limit reached: {count}/{limit}\n"
                "User permanently banned."
                f"{suffix}",
                topic_id=topic_id,
            )
        elif action == "warn_only":
            await send_in_context(
                chat,
                f"⚠️ {name}\n\n"
                f"Warning: {count}/{limit}. "
                "Temporary mute is unavailable in basic groups."
                f"{suffix}",
                topic_id=topic_id,
            )
        else:
            minutes = int(action.split(":", 1)[1])
            await send_in_context(
                chat,
                f"⚠️ {name}\n\n"
                f"Warning: {count}/{limit}\n"
                f"Muted for {minutes} minutes."
                f"{suffix}",
                topic_id=topic_id,
            )
    except Exception:
        logger.exception("Moderation announcement failed")
