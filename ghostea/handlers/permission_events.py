"""H02 lifecycle hooks for invalidating live Telegram authorization caches."""
import logging
from telegram import Update
from telegram.ext import ContextTypes

from ghostea.services.telegram_service import invalidate_admin_cache
from ghostea.services.observability import OBSERVABILITY

logger = logging.getLogger("Ghostea")


async def handle_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    event = update.my_chat_member
    if not event or not event.chat:
        return
    service = context.application.bot_data.get("telegram_permissions")
    if service:
        service.invalidate_chat(event.chat.id)
    invalidate_admin_cache(event.chat.id)

    # H08: the Chat object on lifecycle updates is the freshest identity signal
    # available to the bot. Reconcile type/username/forum state after the
    # permission cache has been invalidated. Private chats are intentionally
    # excluded because the registry is group/supergroup scoped.
    migrations = context.application.bot_data.get("chat_migrations")
    if migrations and getattr(event.chat, "type", None) in {"group", "supergroup"}:
        try:
            await migrations.reconcile_chat(event.chat, reason="my_chat_member")
        except Exception:
            # Permission changes must never fail merely because registry
            # reconciliation is unavailable.
            logger.exception("Chat lifecycle reconciliation failed: chat=%s", event.chat.id)

    OBSERVABILITY.emit("bot_membership_change",
                       chat_id=event.chat.id,
                       status=getattr(event.new_chat_member, "status", "unknown"))
    logger.info("Bot membership/permissions changed: chat=%s status=%s",
                event.chat.id, getattr(event.new_chat_member, "status", "unknown"))


async def handle_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    event = update.chat_member
    if not event or not event.chat or not event.new_chat_member:
        return
    service = context.application.bot_data.get("telegram_permissions")
    if service:
        service.invalidate_member(event.chat.id, event.new_chat_member.user.id)
    invalidate_admin_cache(event.chat.id, event.new_chat_member.user.id)
    OBSERVABILITY.emit("member_status_change",
                       chat_id=event.chat.id,
                       user_id=event.new_chat_member.user.id,
                       status=getattr(event.new_chat_member, "status", "unknown"))
