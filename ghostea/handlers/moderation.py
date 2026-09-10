import logging

from telegram import Update
from telegram.ext import ContextTypes

from ghostea.config import DEFAULT_MAX_WARNINGS
from ghostea.handlers.common import require_admin, target_from_update
from ghostea.services.chat_context import build_chat_context
from ghostea.services.telegram_service import (
    ban_member, mute_member, unban_member, unmute_member, is_admin,
    perform_ban_member, perform_mute_member, perform_unban_member,
    UnsupportedChatFeature,
)
from ghostea.utils import display_name

logger = logging.getLogger("Ghostea")


async def warn_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update):
        return
    target = target_from_update(update)
    if not target:
        await update.effective_message.reply_text("❌ Invalid target.")
        return
    target_admin = await _target_admin(update, target.id)
    if target_admin is None:
        await update.effective_message.reply_text("⚠️ Could not verify target permissions. Action cancelled.")
        return
    if target_admin:
        await update.effective_message.reply_text("❌ Invalid target or target is an admin.")
        return

    chat_context = build_chat_context(update.effective_chat, update.effective_message)
    try:
        count, action = await context.application.bot_data["phase3_moderation"].issue_warning(
            update.effective_chat, target, "Manual warning", "manual",
            topic_id=chat_context.topic_id if chat_context else None,
        )
        await update.effective_message.reply_text(_warning_text(target, count, action, context))
    except Exception as error:
        logger.exception("Manual warning failed: %s", error)
        await update.effective_message.reply_text("❌ Warning failed. Check bot permissions/database.")


async def unwarn_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update):
        return
    target = target_from_update(update)
    store = context.application.bot_data["phase3_store"]
    count = await store.remove_warning(update.effective_chat.id, target.id)
    chat_context = build_chat_context(update.effective_chat, update.effective_message)
    await store.log(update.effective_chat.id, target.id, "UNWARN", "Admin removed warning", "",
                    topic_id=chat_context.topic_id if chat_context else None)
    await update.effective_message.reply_text(
        f"↩️ {display_name(target)}\nWarnings: {count}/{await _max_warnings(update, context)}"
    )


async def resetwarnings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update):
        return
    target = target_from_update(update)
    store = context.application.bot_data["phase3_store"]
    await store.reset_warnings(update.effective_chat.id, target.id)
    await update.effective_message.reply_text(
        f"♻️ Warnings reset for {display_name(target)}.\n"
        f"Warnings: 0/{await _max_warnings(update, context)}"
    )


async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update):
        return
    target = target_from_update(update)
    target_admin = await _target_admin(update, target.id)
    if target_admin is None:
        await update.effective_message.reply_text("⚠️ Could not verify target permissions. Ban cancelled.")
        return
    if target_admin:
        await update.effective_message.reply_text("❌ Admins cannot be banned by this bot.")
        return
    try:
        result = await perform_ban_member(update.effective_chat, target.id, context.application.bot_data.get("telegram_permissions"), requester_id=update.effective_user.id)
        if not result.ok:
            await update.effective_message.reply_text(f"❌ Ban failed ({result.status.value}).")
            return
        await context.application.bot_data["phase3_store"].log(
            update.effective_chat.id, target.id, "BAN", "Manual ban", "",
            topic_id=_topic_id(update),
        )
        await update.effective_message.reply_text(f"🚫 {display_name(target)} has been banned.")
    except Exception as error:
        logger.exception("Ban failed: %s", error)
        await update.effective_message.reply_text("❌ Ban failed. Check Ban Members permission.")


async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update):
        return
    target = target_from_update(update)
    try:
        result = await perform_unban_member(update.effective_chat, target.id, context.application.bot_data.get("telegram_permissions"))
        if not result.ok:
            await update.effective_message.reply_text(f"❌ Unban failed ({result.status.value}).")
            return
        await context.application.bot_data["phase3_store"].log(
            update.effective_chat.id, target.id, "UNBAN", "Manual unban", "",
            topic_id=_topic_id(update),
        )
        await update.effective_message.reply_text(f"✅ {display_name(target)} has been unbanned.")
    except Exception as error:
        logger.exception("Unban failed: %s", error)
        await update.effective_message.reply_text("❌ Unban failed.")


async def mute_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update):
        return
    target = target_from_update(update)
    minutes = _parse_duration(context.args)
    if minutes is None:
        await update.effective_message.reply_text("Usage: reply to a user with /mute 10m, /mute 1h or /mute 1d")
        return
    try:
        result = await perform_mute_member(update.effective_chat, target.id, minutes, context.application.bot_data.get("telegram_permissions"), requester_id=update.effective_user.id)
        if not result.ok:
            await update.effective_message.reply_text(f"❌ Mute failed ({result.status.value}).")
            return
        await context.application.bot_data["phase3_store"].log(
            update.effective_chat.id, target.id, "MUTE", "Manual mute", f"minutes={minutes}",
            topic_id=_topic_id(update),
        )
        await update.effective_message.reply_text(f"🔇 {display_name(target)} muted for {minutes} minute(s).")
    except UnsupportedChatFeature:
        await update.effective_message.reply_text(
            "ℹ️ Temporary member mutes are not supported in basic Telegram groups. "
            "Use a supergroup for per-member restrictions."
        )
    except Exception as error:
        logger.exception("Mute failed: %s", error)
        await update.effective_message.reply_text("❌ Mute failed. Check Restrict Members permission.")


async def unmute_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update):
        return
    target = target_from_update(update)
    try:
        await unmute_member(update.effective_chat, target.id, permission_service=context.application.bot_data.get("telegram_permissions"))
        await context.application.bot_data["phase3_store"].log(
            update.effective_chat.id, target.id, "UNMUTE", "Manual unmute", "",
            topic_id=_topic_id(update),
        )
        await update.effective_message.reply_text(
            f"🔊 {display_name(target)} has been unmuted."
        )
    except UnsupportedChatFeature:
        await update.effective_message.reply_text(
            "ℹ️ Per-member unmute is not supported in basic Telegram groups."
        )
    except Exception as error:
        logger.exception("Unmute failed: %s", error)
        await update.effective_message.reply_text("❌ Unmute failed.")


async def reloadfilters_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update):
        return

    abuse_filter = context.application.bot_data["abuse_filter"]
    spam_patterns = context.application.bot_data["spam_patterns"]
    blocked_domains = context.application.bot_data["blocked_domains"]

    try:
        a = abuse_filter.reload()
        s = spam_patterns.reload()
        d = blocked_domains.reload()
        await update.effective_message.reply_text(
            f"🔄 Filters reloaded.\nAbuse: {a}\nSpam patterns: {s}\nBlocked domains: {d}"
        )
    except Exception as error:
        logger.exception("Filter reload failed: %s", error)
        await update.effective_message.reply_text("❌ Could not reload filter files.")


def _topic_id(update):
    chat_context = build_chat_context(update.effective_chat, update.effective_message)
    return chat_context.topic_id if chat_context else None


async def _target_admin(update, user_id):
    try:
        return await is_admin(update.effective_chat, user_id)
    except Exception:
        # H06: unknown authorization state must never be treated as
        # "not an admin" for destructive commands.
        return None


async def _max_warnings(update, context):
    return (await context.application.bot_data["phase3_store"].get_settings(
        update.effective_chat.id
    ))["max_warnings"]


def _warning_text(target, count, action, context):
    name = display_name(target)
    # The caller only needs display text; limit is resolved from DB in the command flow.
    if action == "ban":
        return f"🚫 {name}\n\nWarning limit reached: {count}\nUser permanently banned."
    if action.startswith("ban_failed:"):
        return f"⚠️ {name}\n\nWarning: {count}\nBan action could not be completed ({action.split(':', 1)[1]})."
    if action.startswith("mute_failed:"):
        return f"⚠️ {name}\n\nWarning: {count}\nMute action could not be completed ({action.split(':', 1)[1]})."
    if action == "warn_only":
        return (
            f"⚠️ {name}\n\n"
            f"Warning: {count}\n"
            "Temporary mute is unavailable in basic groups."
        )
    minutes = int(action.split(":")[1])
    return f"⚠️ {name}\n\nWarning: {count}\nMuted for {minutes} minutes."


def _parse_duration(args):
    if not args:
        return None
    value = args[0].strip().lower()
    units = {
        "m": 1, "min": 1, "mins": 1,
        "h": 60, "hr": 60, "hrs": 60,
        "d": 1440, "day": 1440, "days": 1440,
    }
    for suffix, multiplier in units.items():
        if value.endswith(suffix):
            number = value[:-len(suffix)]
            if number.isdigit() and int(number) > 0:
                return int(number) * multiplier
    return None
