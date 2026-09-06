"""Phase 15 — forum topic management commands."""
import logging

from telegram import Update
from telegram.ext import ContextTypes

from ghostea.handlers.common import require_admin, require_topic_manager
from ghostea.services.chat_context import build_chat_context
from ghostea.services.forum_topic_service import (
    ForumTopicError, ForumTopicService, GENERAL_TOPIC_ID
)

logger = logging.getLogger("Ghostea")


def _service(context):
    return context.application.bot_data["forum_topics"]


def _topic_id(update, context=None):
    enabled = bool(
        context.application.bot_data.get("private_topics_enabled", False)
    ) if context else False
    ctx = build_chat_context(
        update.effective_chat,
        update.effective_message,
        private_topics_enabled=enabled,
    )
    return ctx.topic_id if ctx else None


async def topics_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_topic_manager(update, context):
        return
    try:
        rows = await _service(context).list_topics(update.effective_chat, limit=50)
        if not rows:
            await update.effective_message.reply_text("No Ghostea topic records yet.")
            return
        lines = ["🧵 Topics:"]
        for row in rows:
            state = "closed" if row.get("is_closed") else "open"
            if not row.get("is_active", True):
                state = "deleted"
            lines.append(
                f"• {row.get('name') or 'Unnamed'} — ID {row.get('topic_id')} — {state}"
            )
        await update.effective_message.reply_text("\n".join(lines))
    except ForumTopicError as exc:
        await update.effective_message.reply_text(f"ℹ️ {exc}")
    except Exception:
        logger.exception("Topic list failed")
        await update.effective_message.reply_text("❌ Could not load forum topics.")


async def topiccreate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_topic_manager(update, context):
        return
    title = " ".join(context.args).strip()
    try:
        topic = await _service(context).create_topic(update.effective_chat, title)
        await update.effective_message.reply_text(
            f"🧵 Topic created: {getattr(topic, 'name', title)} "
            f"(ID {getattr(topic, 'message_thread_id', '?')})"
        )
    except ForumTopicError as exc:
        await update.effective_message.reply_text(f"ℹ️ {exc}")
    except Exception:
        logger.exception("Topic creation failed")
        await update.effective_message.reply_text("❌ Topic creation failed.")


def _resolve_id(update, context):
    if context.args:
        return context.args[0]
    return _topic_id(update)


async def topicrename_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_topic_manager(update, context):
        return
    if not context.args:
        await update.effective_message.reply_text(
            "Usage: /topicrename <new name> (run inside the topic)"
        )
        return
    topic_id = _topic_id(update, context)
    title = " ".join(context.args).strip()
    try:
        await _service(context).rename_topic(update.effective_chat, topic_id, title)
        await update.effective_message.reply_text("✏️ Topic renamed.")
    except ForumTopicError as exc:
        await update.effective_message.reply_text(f"ℹ️ {exc}")
    except Exception:
        logger.exception("Topic rename failed")
        await update.effective_message.reply_text("❌ Topic rename failed.")


async def topicclose_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_topic_manager(update, context):
        return
    topic_id = _resolve_id(update, context)
    try:
        await _service(context).close_topic(update.effective_chat, topic_id)
        await update.effective_message.reply_text("🔒 Topic closed.")
    except ForumTopicError as exc:
        await update.effective_message.reply_text(f"ℹ️ {exc}")
    except Exception:
        logger.exception("Topic close failed")
        await update.effective_message.reply_text("❌ Topic close failed.")


async def topicreopen_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_topic_manager(update, context):
        return
    topic_id = _resolve_id(update, context)
    try:
        await _service(context).reopen_topic(update.effective_chat, topic_id)
        await update.effective_message.reply_text("🔓 Topic reopened.")
    except ForumTopicError as exc:
        await update.effective_message.reply_text(f"ℹ️ {exc}")
    except Exception:
        logger.exception("Topic reopen failed")
        await update.effective_message.reply_text("❌ Topic reopen failed.")


async def topicdelete_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_topic_manager(update, context):
        return
    topic_id = _resolve_id(update, context)
    try:
        await _service(context).delete_topic(update.effective_chat, topic_id)
        await update.effective_message.reply_text("🗑️ Topic deleted.")
    except ForumTopicError as exc:
        await update.effective_message.reply_text(f"ℹ️ {exc}")
    except Exception:
        logger.exception("Topic deletion failed")
        await update.effective_message.reply_text("❌ Topic deletion failed.")
