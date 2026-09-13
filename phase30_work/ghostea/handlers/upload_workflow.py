"""Phase 6 Telegram UI adapter for the shared upload workflow engine."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatType
from telegram.ext import ContextTypes

from ghostea.services.resource_publishing import ResourcePublishError
from ghostea.services.upload_workflow import (
    UploadState, UploadWorkflowError, UploadMode, MAX_GROUPS, MAX_TOPICS,
)

PREFIX = "upload:"

def _kb(rows):
    return InlineKeyboardMarkup(rows)

def _session_id(data):
    parts = data.split(":")
    if len(parts) < 2 or not parts[1]:
        raise UploadWorkflowError("Invalid workflow callback.")
    return parts[1]

def _group_keyboard(session):
    return _kb([[InlineKeyboardButton(g["title"][:48], callback_data=f"upload:{session.session_id}:g:{i}")] for i,g in enumerate(session.payload.get("groups", []))])

def _topic_keyboard(session):
    rows=[]
    for i,t in enumerate(session.payload.get("topics", [])):
        rows.append([InlineKeyboardButton(t["name"][:48], callback_data=f"upload:{session.session_id}:t:{i}")])
    return _kb(rows)

def _confirm_keyboard(session):
    return _kb([[InlineKeyboardButton("⬆️ Upload", callback_data=f"upload:{session.session_id}:confirm"), InlineKeyboardButton("❌ Cancel", callback_data=f"upload:{session.session_id}:cancel")]])

def _source_keyboard(session):
    return _kb([[InlineKeyboardButton("📎 File", callback_data=f"upload:{session.session_id}:file"), InlineKeyboardButton("🔗 URL", callback_data=f"upload:{session.session_id}:url")], [InlineKeyboardButton("❌ Cancel", callback_data=f"upload:{session.session_id}:cancel")]])

async def _send_state(message, session):
    if session.state == UploadState.SELECT_GROUP.value:
        await message.reply_text("1/… Select the group:", reply_markup=_group_keyboard(session))
    elif session.state == UploadState.SELECT_TOPIC.value:
        await message.reply_text("Select the topic:", reply_markup=_topic_keyboard(session))
    elif session.state == UploadState.SELECT_SOURCE.value:
        await message.reply_text("What do you want to upload?", reply_markup=_source_keyboard(session))
    elif session.state == UploadState.WAIT_FILE.value:
        await message.reply_text("📎 Send the file now.")
    elif session.state == UploadState.WAIT_URL.value:
        await message.reply_text("🔗 Send the http/https URL now.")
    elif session.state == UploadState.WAIT_CAPTION.value:
        await message.reply_text("✍️ Send the caption. It is mandatory.")
    elif session.state == UploadState.WAIT_DESCRIPTION.value:
        await message.reply_text("📝 Send the description. It is mandatory.")
    elif session.state == UploadState.WAIT_FLAG_IMAGE.value:
        await message.reply_text("🖼️ Send the flag image now.")
    elif session.state == UploadState.WAIT_MAIN_FLAG.value:
        await message.reply_text("Send Main-Flag in copy-friendly text format.")
    elif session.state == UploadState.WAIT_SUB_FLAGS.value:
        await message.reply_text("Send Sub-Flags in copy-friendly text format.")
    elif session.state == UploadState.WAIT_FLAG_DESCRIPTION.value:
        await message.reply_text("Send the flag description. It is mandatory.")
    elif session.state == UploadState.CONFIRM.value:
        p=session.payload
        target=p.get("selected_group",{}).get("title") or session.chat_id
        topic=(p.get("selected_topic") or {}).get("name") or "No topic"
        if session.mode == UploadMode.RESOURCE.value:
            source=p.get("source",{}); src=source.get("file_name") or source.get("url") or source.get("kind")
            text=f"📦 <b>Upload preview</b>\nGroup: {target}\nTopic: {topic}\nSource: {src}\nCaption: {p.get('caption')}\nDescription: {p.get('description')}\n\nConfirm?"
        else:
            text=f"🚩 <b>Flag preview</b>\nGroup: {target}\nTopic: {topic}\nMain-Flag: {p.get('main_flag')}\nSub-Flags: {p.get('sub_flags')}\nDescription: {p.get('description')}\n\nConfirm?"
        await message.reply_html(text, reply_markup=_confirm_keyboard(session))
    elif session.state == UploadState.WAIT_MAIN_FLAG.value:
        pass

async def uploadconfig_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_chat.type != ChatType.PRIVATE:
        await update.effective_message.reply_text("ℹ️ Use /uploadconfig in the bot's DM.")
        return
    engine=context.application.bot_data["upload_workflow"]
    try:
        session=await engine.start(update.effective_user.id, UploadMode.RESOURCE)
        await update.effective_message.reply_text("👻 Upload Config started. Your admin access will be checked again before upload.")
        await _send_state(update.effective_message, session)
    except UploadWorkflowError as exc:
        await update.effective_message.reply_text(str(exc))

async def uploadflag_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_chat.type != ChatType.PRIVATE:
        await update.effective_message.reply_text("ℹ️ Use /uploadflag in the bot's DM.")
        return
    engine=context.application.bot_data["upload_workflow"]
    try:
        session=await engine.start(update.effective_user.id, UploadMode.FLAG)
        await update.effective_message.reply_text("👻 Upload Flag started. Your admin access will be checked again before upload.")
        await _send_state(update.effective_message, session)
        if session.state == UploadState.SELECT_GROUP.value:
            pass
    except UploadWorkflowError as exc:
        await update.effective_message.reply_text(str(exc))

async def upload_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query
    if not q or not update.effective_user:
        return
    await q.answer()
    engine=context.application.bot_data["upload_workflow"]
    try:
        parts=q.data.split(":")
        session_id=_session_id(q.data); action=parts[2] if len(parts)>2 else ""
        if action == "g": session=await engine.select_group(session_id, update.effective_user.id, parts[3])
        elif action == "t": session=await engine.select_topic(session_id, update.effective_user.id, parts[3])
        elif action in ("file","url"): session=await engine.choose_source(session_id, update.effective_user.id, action)
        elif action == "cancel":
            session=await engine.cancel(session_id, update.effective_user.id)
            await q.edit_message_text("❌ Upload cancelled."); return
        elif action == "confirm":
            await engine.confirm(session_id, update.effective_user.id)
            publisher = context.application.bot_data["resource_publishing"]
            resource_id = await publisher.publish(session_id, update.effective_user.id)
            await q.edit_message_text(
                f"✅ Upload published successfully.\nResource ID: <code>{resource_id}</code>",
                parse_mode="HTML",
            )
            return
        else: raise UploadWorkflowError("Invalid workflow action.")
        await q.edit_message_text("Selection saved.")
        await _send_state(q.message, session)
    except UploadWorkflowError as exc:
        await q.edit_message_text(str(exc))

async def upload_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.effective_chat or update.effective_chat.type != ChatType.PRIVATE:
        return
    engine=context.application.bot_data["upload_workflow"]
    # Only active sessions are considered; unrelated DMs pass through silently.
    try:
        # We do not have a per-user current-session index by design. Fetch the
        # latest active session for the user from durable storage.
        session = await engine.store.latest_active_upload_session(update.effective_user.id)
        if not session:
            return
        s=engine._as_session(session)
        if s.state in (UploadState.WAIT_FILE.value, UploadState.WAIT_URL.value):
            s=await engine.receive_resource(s.session_id, update.effective_user.id, update.effective_message)
        elif s.state == UploadState.WAIT_CAPTION.value:
            s=await engine.receive_caption(s.session_id, update.effective_user.id, update.effective_message.text)
        elif s.state == UploadState.WAIT_DESCRIPTION.value:
            s=await engine.receive_description(s.session_id, update.effective_user.id, update.effective_message.text)
        elif s.state == UploadState.WAIT_FLAG_IMAGE.value:
            s=await engine.receive_flag_image(s.session_id, update.effective_user.id, update.effective_message)
        elif s.state == UploadState.WAIT_MAIN_FLAG.value:
            s=await engine.receive_flag_text(s.session_id, update.effective_user.id, update.effective_message.text, "main")
        elif s.state == UploadState.WAIT_SUB_FLAGS.value:
            s=await engine.receive_flag_text(s.session_id, update.effective_user.id, update.effective_message.text, "sub")
        elif s.state == UploadState.WAIT_FLAG_DESCRIPTION.value:
            s=await engine.receive_flag_text(s.session_id, update.effective_user.id, update.effective_message.text, "description")
        else:
            return
        await _send_state(update.effective_message, s)
    except UploadWorkflowError as exc:
        await update.effective_message.reply_text(str(exc))


async def resource_download_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q or not update.effective_user:
        return
    await q.answer()
    publisher = context.application.bot_data["resource_publishing"]
    try:
        resource_id = str(q.data).split(":", 1)[1]
        await publisher.deliver_download(resource_id, update.effective_user.id)
    except ResourcePublishError as exc:
        await q.answer(str(exc), show_alert=True)
    except Exception:
        await q.answer("❌ Download failed. Please try again later.", show_alert=True)


async def link_group_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Explicitly bootstrap/reconcile a group for DM upload discovery.

    Telegram cannot enumerate all groups a bot is in. This command provides a
    deterministic fallback for an existing group that predates Ghostea's
    lifecycle registry or whose pending my_chat_member update was lost.
    """
    chat = update.effective_chat
    user = update.effective_user
    if not chat or chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        if update.effective_message:
            await update.effective_message.reply_text(
                "ℹ️ Use /link in the Telegram group you want to connect to Ghostea."
            )
        return

    permissions = context.application.bot_data["telegram_permissions"]
    try:
        bot_perms = await permissions.bot_permissions(chat, force=True)
        if not bot_perms.is_admin:
            await update.effective_message.reply_text(
                "❌ Ghostea Bot must be an administrator in this group first."
            )
            return

        if not await permissions.is_admin(chat, user.id, force=True):
            await update.effective_message.reply_text(
                "❌ Only a current Telegram group admin can link this group."
            )
            return

        from ghostea.services.chat_context import build_chat_context
        migrations = context.application.bot_data["chat_migrations"]
        chat_context = build_chat_context(chat)
        if not chat_context:
            raise RuntimeError("Unsupported Telegram chat type.")

        await migrations.reconcile_chat(chat_context, reason="explicit_link")
        await update.effective_message.reply_text(
            "✅ This group is linked to Ghostea. You can now open the bot DM and use /uploadconfig or /uploadflag."
        )
    except Exception:
        await update.effective_message.reply_text(
            "❌ I couldn't link this group right now. Please verify the bot is an administrator and try again."
        )
