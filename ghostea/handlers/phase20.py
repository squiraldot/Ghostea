"""Phase 20 — final compatibility/production diagnostics."""
import logging

from telegram import Update
from telegram.ext import ContextTypes

from ghostea.handlers.common import require_admin
from ghostea.services.chat_capabilities import resolve_bot_permissions
from ghostea.services.chat_context import build_chat_context
from ghostea.services.chat_visibility import resolve_chat_visibility
from ghostea.services.production_readiness import compatibility_matrix, local_readiness, readiness_summary

logger = logging.getLogger("Ghostea")


async def compatibility_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update):
        return
    chat = update.effective_chat
    message = update.effective_message
    private_topics = bool(context.application.bot_data.get("private_topics_enabled", False))
    chat_context = build_chat_context(chat, message, private_topics_enabled=private_topics)
    if not chat_context:
        await message.reply_text("ℹ️ This chat type is not supported by Ghostea.")
        return

    caps = chat_context.capabilities
    visibility = resolve_chat_visibility(chat_context)
    lines = [
        "👻 Ghostea Compatibility",
        "",
        f"Chat: {caps.kind}",
        f"Visibility: {visibility.visibility}",
        f"Moderation: {'Yes' if caps.supports_member_moderation else 'No'}",
        f"Message deletion: {'Yes' if caps.supports_message_deletion else 'No'}",
        f"Member restriction: {'Yes' if caps.supports_member_restriction else 'No'}",
        f"Member ban: {'Yes' if caps.supports_member_ban else 'No'}",
        f"Topics: {'Yes' if caps.supports_topics else 'No'}",
    ]

    if chat_context.is_private_chat:
        lines.append(f"Private topic mode: {'Enabled' if private_topics else 'Disabled'}")
    elif caps.is_supergroup:
        try:
            me = await context.bot.get_me()
            permissions = await resolve_bot_permissions(chat, me.id)
            lines.extend([
                f"Bot admin: {'Yes' if permissions.is_admin else 'No'}",
                f"Delete messages: {'Yes' if permissions.can_delete_messages else 'No'}",
                f"Restrict members: {'Yes' if permissions.can_restrict_members else 'No'}",
                f"Ban members: {'Yes' if permissions.can_ban_members else 'No'}",
                f"Manage topics: {'Yes' if permissions.can_manage_topics else 'No'}",
            ])
        except Exception:
            logger.exception("Live compatibility permission check failed")
            lines.append("Bot permissions: unavailable")

    await message.reply_text("\n".join(lines))


async def readiness_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update):
        return
    summary = readiness_summary(local_readiness())
    status = "READY" if summary["ready"] else "NOT READY"
    lines = [f"🏥 Ghostea Production Readiness: {status}", ""]
    for check in summary["checks"]:
        lines.append(f"{'✅' if check['ok'] else '❌'} {check['name']}: {check['detail']}")
    await update.effective_message.reply_text("\n".join(lines))
