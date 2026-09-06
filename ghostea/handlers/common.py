import logging
from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger("Ghostea")

from ghostea.services.telegram_service import is_admin
from ghostea.services.chat_context import build_chat_context
from ghostea.services.chat_visibility import resolve_chat_visibility
from ghostea.utils import display_name, get_target_user


async def require_admin(update: Update) -> bool:
    chat = update.effective_chat
    user = update.effective_user

    if not build_chat_context(chat, update.effective_message) or not user:
        return False

    try:
        return await is_admin(chat, user.id)
    except Exception:
        return False


async def require_topic_manager(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Authorize forum-topic commands for supergroups and private topic chats."""
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user or not update.effective_message:
        return False

    if getattr(chat, "type", None) == "private":
        try:
            me = await context.bot.get_me()
            if not bool(getattr(me, "has_topics_enabled", False)):
                await update.effective_message.reply_text(
                    "ℹ️ Private-chat topics are not enabled for Ghostea. Enable forum topic mode for this bot in BotFather."
                )
                return False
            return True
        except Exception:
            return False

    return await require_admin(update)


def target_from_update(update: Update):
    return get_target_user(update)


async def chatinfo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show safe chat/capability diagnostics, including private topic mode."""
    chat = update.effective_chat
    message = update.effective_message
    if not chat or not message:
        return

    private_topics_enabled = bool(
        context.application.bot_data.get("private_topics_enabled", False)
    )
    chat_context = build_chat_context(
        chat, message, private_topics_enabled=private_topics_enabled
    )
    registration_error = None
    if chat_context and chat_context.is_supported:
        try:
            store = context.application.bot_data.get("phase3_store")
            if store:
                await store.touch_chat(chat_context)
            else:
                registration_error = "database_store_unavailable"
        except Exception as exc:
            registration_error = str(exc)
            logger.exception("Chat info registration failed: chat=%s", chat.id)
    if not chat_context:
        await message.reply_text("ℹ️ This chat type is not supported by Ghostea.")
        return

    caps = chat_context.capabilities
    lines = [
        "👻 Ghostea Chat Info",
        f"Type: {chat_context.chat_type}",
        f"Visibility: {chat_context.visibility}",
        f"Forum: {'Yes' if chat_context.is_forum else 'No'}",
        f"Topic mode: {'Yes' if caps.supports_topics else 'No'}",
        f"Current topic: {chat_context.topic_id if chat_context.topic_id is not None else '—'}",
    ]
    if chat_context.is_private_chat:
        lines.append(
            f"Private topic mode: {'Enabled' if private_topics_enabled else 'Disabled'}"
        )
    if registration_error:
        lines.append("")
        lines.append("⚠️ Database registration failed. Check Render logs and Supabase schema.")
    else:
        lines.append("")
        lines.append("✅ Registered in Ghostea dashboard.")
    await message.reply_text("\n".join(lines))


async def warnings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    requester = update.effective_user

    if not chat or not requester or not update.effective_message:
        return

    target = target_from_update(update)

    # Members can only see their own warnings.
    # Admins can inspect a target by replying to that user's message.
    if target.id != requester.id:
        try:
            if not await is_admin(chat, requester.id):
                target = requester
        except Exception:
            target = requester

    store = context.application.bot_data["phase3_store"]
    count = await store.get_warning_count(chat.id, target.id)
    settings = await store.get_settings(chat.id)
    limit = int(settings.get("max_warnings", 3))

    await update.effective_message.reply_text(
        f"⚠️ {display_name(target)}\n"
        f"Warnings: {count}/{limit}"
    )


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "Ghostea👻 is online!\n"
        "Group moderation is active."
    )


async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not build_chat_context(update.effective_chat, update.effective_message):
        return

    from ghostea.services.telegram_service import is_admin
    if not await is_admin(update.effective_chat, update.effective_user.id):
        return

    store = context.application.bot_data["phase3_store"]
    chat_context = build_chat_context(update.effective_chat, update.effective_message)
    topic_id = chat_context.topic_id if chat_context else None
    s = await store.get_effective_settings(update.effective_chat.id, topic_id)
    scope_label = f"Topic {topic_id}" if topic_id is not None else "Chat-wide"

    await update.effective_message.reply_text(
        "⚙️ Ghostea Settings\n"
        f"Scope: {scope_label}\n\n"
        f"Warnings: {s['max_warnings']}\n"
        f"1st mute: {s['mute1_minutes']} min\n"
        f"2nd mute: {s['mute2_minutes']} min\n"
        f"Flood: {s['flood_message_limit']} msgs / {s['flood_window_seconds']} sec\n"
        f"Flood mute: {s['flood_mute_minutes']} min\n"
        f"Link action: {s['blocked_link_action']}\n\n"
        f"Abuse filter: {'ON' if s['abuse_filter_enabled'] else 'OFF'}\n"
        f"Spam filter: {'ON' if s['spam_filter_enabled'] else 'OFF'}\n"
        f"Link filter: {'ON' if s['link_filter_enabled'] else 'OFF'}\n"
        f"Flood protection: {'ON' if s['flood_protection_enabled'] else 'OFF'}"
    )


async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    requester = update.effective_user
    if not chat or not requester:
        return

    target = target_from_update(update)
    if target.id != requester.id:
        try:
            if not await is_admin(chat, requester.id):
                target = requester
        except Exception:
            target = requester

    store = context.application.bot_data["phase3_store"]
    rows = await store.get_history(update.effective_chat.id, target.id, 10)

    if not rows:
        await update.effective_message.reply_text(
            f"📋 No warning history for {display_name(target)}."
        )
        return

    lines = [f"📋 Warning history — {display_name(target)}", ""]
    for i, row in enumerate(rows, 1):
        lines.append(
            f"{i}. {row['reason']} [{row['source']}]"
        )

    await update.effective_message.reply_text("\n".join(lines))
