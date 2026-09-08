import os
import logging
import asyncio

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChatMemberHandler,
    CommandHandler,
    MessageHandler,
    TypeHandler,
    ApplicationHandlerStop,
    filters,
)

from ghostea.config import (
    BLOCKED_DOMAINS_FILE,
    DATA_FILE,
    FILTERS_FILE,
    SPAM_PATTERNS_FILE,
    SUPABASE_KEY,
    SUPABASE_URL,
    TOKEN,
    DEFAULT_SPAM_MESSAGE_LIMIT,
    DEFAULT_SPAM_WINDOW_SECONDS,
)
from ghostea.filters.line_loader import LineList
from ghostea.filters.loader import AbuseFilter
from ghostea.handlers.common import (
    history_command,
    settings_command,
    start_command,
    warnings_command, chatinfo_command,
)
from ghostea.handlers.messages import check_message
from ghostea.handlers.moderation import (
    ban_command, mute_command, reloadfilters_command,
    resetwarnings_command, unban_command, unmute_command,
    unwarn_command, warn_command,
)
from ghostea.handlers.settings import (
    addfilter_command, delfilter_command, filters_command,
    logs_command, setflood_command, setfloodmute_command,
    setlinkaction_command, setmute1_command, setmute2_command,
    setwarnlimit_command, toggle_command,
)
from ghostea.handlers.phase4 import (
    handle_new_members, raidmode_command, setraid_command,
    stats_command, welcome_command,
)
from ghostea.handlers.phase5 import (
    reputation_command, setmaxmsg_command,
    setverification_command, verification_command, verify_callback,
)
from ghostea.handlers.phase6 import analytics_command, export_command, health_command
from ghostea.handlers.phase20 import compatibility_command, readiness_command
from ghostea.handlers.forum_topics import (
    topics_command, topiccreate_command, topicrename_command,
    topicclose_command, topicreopen_command, topicdelete_command,
)
from ghostea.logging_config import setup_logging
from ghostea.services.analytics_service import AnalyticsService
from ghostea.services.admin_service import AdminService
from ghostea.services.moderation_engine import ModerationEngine
from ghostea.services.phase3_moderation import Phase3ModerationService
from ghostea.services.protection_service import ProtectionService
from ghostea.services.verification_service import VerificationService
from ghostea.services.security_service import SecurityService
from ghostea.services.risk_service import RiskService
from ghostea.services.user_management_service import UserManagementService
from ghostea.services.chat_migration_service import ChatMigrationService
from ghostea.services.forum_topic_service import ForumTopicService
from ghostea.services.production_readiness import local_readiness, readiness_summary
from ghostea.services.permission_service import TelegramPermissionService
from ghostea.services.state_recovery import StateRecoveryService
from ghostea.services.telegram_resilience import TelegramErrorPolicy
from ghostea.services.group_authorization import GroupAuthorizationService
from ghostea.services.concurrency import UpdateDeduplicator
from ghostea.services.observability import OBSERVABILITY, new_request_id, set_request_id, reset_request_id
from ghostea.storage.database import SupabaseREST
from ghostea.storage.phase3_store import Phase3Store
from ghostea.web_server import start_web_server


def create_application():
    logger = setup_logging()

    if not TOKEN:
        raise RuntimeError("BOT_TOKEN is not configured.")
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_KEY are required."
        )
    if not os.getenv("DASHBOARD_API_KEY", "").strip():
        raise RuntimeError("DASHBOARD_API_KEY is required.")
    if not os.getenv("DASHBOARD_ORIGIN", "").strip():
        raise RuntimeError("DASHBOARD_ORIGIN is required.")

    readiness = readiness_summary(local_readiness())
    if not readiness["ready"]:
        logger.warning("Ghostea production readiness has failed checks: %s", readiness["checks"])

    abuse_filter = AbuseFilter(FILTERS_FILE)
    spam_patterns = LineList(SPAM_PATTERNS_FILE)
    blocked_domains = LineList(BLOCKED_DOMAINS_FILE)

    db = SupabaseREST(SUPABASE_URL, SUPABASE_KEY)
    store = Phase3Store(db)
    protection = ProtectionService(
        spam_patterns,
        blocked_domains,
        DEFAULT_SPAM_WINDOW_SECONDS,
        DEFAULT_SPAM_MESSAGE_LIMIT,
    )
    moderation = Phase3ModerationService(store)
    moderation_engine = ModerationEngine(abuse_filter, protection)
    analytics = AnalyticsService(store)
    admins = AdminService(store)
    verification = VerificationService(store)
    security = SecurityService(store, None)  # bot/permissions are attached after Application creation
    risk = RiskService(store)
    chat_migrations = ChatMigrationService(store)
    forum_topics = ForumTopicService(store, None)  # bot/permissions attached after Application creation

    async def post_init(application):
        try:
            from ghostea.storage.migration import migrate_json_if_needed
            count = await migrate_json_if_needed(store, DATA_FILE)
            if count:
                logger.info("Migrated %s warning records.", count)
        except Exception:
            logger.exception("Warning migration failed")

        # Bot API 9.3: private-chat forum topic mode is a bot-account setting.
        try:
            me = await telegram_error_policy.call_read(application.bot.get_me)
            application.bot_data["private_topics_enabled"] = bool(
                getattr(me, "has_topics_enabled", False)
            )
            application.bot_data["private_topics_users_can_manage"] = bool(
                getattr(me, "allows_users_to_create_topics", False)
            )
            logger.info(
                "Private chat topics: enabled=%s users_can_manage=%s",
                application.bot_data["private_topics_enabled"],
                application.bot_data["private_topics_users_can_manage"],
            )
        except Exception:
            logger.exception("Private topic capability discovery failed")
            application.bot_data["private_topics_enabled"] = False
            application.bot_data["private_topics_users_can_manage"] = False

        # Persistent security recovery: raid locks and verification expiry.
        try:
            security.bot = application.bot
            recovery = StateRecoveryService(
                store, protection, security, permission_service=permission_service
            )
            recovery_result = await recovery.recover()
            application.bot_data["security"] = security
            application.bot_data["state_recovery"] = recovery
            logger.info("Ghostea state recovery completed: %s", recovery_result)
        except Exception:
            logger.exception("Security recovery failed")
            raise

        # Render health/API server.
        try:
            server = start_web_server(
                store, analytics, application.bot, risk, admins,
                loop=asyncio.get_running_loop(),
                production_readiness=application.bot_data.get("production_readiness", {}),
                permission_service=permission_service,
            )
            application.bot_data["web_server"] = server
            logger.info("Ghostea web server started.")
        except Exception:
            logger.exception("Web server failed to start")
            raise

    async def post_shutdown(application):
        try:
            await security.stop()
        except Exception:
            logger.exception("Security service shutdown failed")

        server = application.bot_data.get("web_server")
        if server:
            server.shutdown()
            server.server_close()

    application = (
        Application.builder()
        .token(TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    permission_service = TelegramPermissionService(application.bot)
    telegram_error_policy = TelegramErrorPolicy()
    update_deduplicator = UpdateDeduplicator(ttl_seconds=180, max_entries=20000)
    chat_migrations.attach_runtime(
        bot=application.bot,
        permission_service=permission_service,
    )
    security.permission_service = permission_service
    moderation.bot = application.bot
    moderation.permission_service = permission_service
    user_management = UserManagementService(store, application.bot, permission_service=permission_service)
    group_authorization = GroupAuthorizationService(store, permission_service)
    forum_topics.bot = application.bot
    forum_topics.permission_service = permission_service

    application.bot_data.update({
        "abuse_filter": abuse_filter,
        "spam_patterns": spam_patterns,
        "blocked_domains": blocked_domains,
        "protection": protection,
        "phase3_store": store,
        "phase3_moderation": moderation,
        "analytics": analytics,
        "admins": admins,
        "user_management": user_management,
        "group_authorization": group_authorization,
        "verification": verification,
        "security": security,
        "risk": risk,
        "moderation": moderation,
        "moderation_engine": moderation_engine,
        "chat_migrations": chat_migrations,
        "forum_topics": forum_topics,
        "production_readiness": readiness,
        "telegram_permissions": permission_service,
        "telegram_error_policy": telegram_error_policy,
        "update_deduplicator": update_deduplicator,
        "observability": OBSERVABILITY,
    })

    async def establish_update_context(update, context):
        token = set_request_id(new_request_id("tg"))
        context.chat_data["_ghostea_request_token"] = token
        OBSERVABILITY.emit(
            "update_received",
            update_id=getattr(update, "update_id", None),
            update_kind=type(update).__name__,
        )

    application.add_handler(TypeHandler(Update, establish_update_context), group=-2)

    # H10 — suppress duplicate Telegram updates before any user-visible or
    # destructive handler executes. First delivery is allowed; duplicates are
    # stopped for a bounded TTL to avoid double warnings/actions.
    async def deduplicate_update(update, context):
        dedup = context.application.bot_data.get("update_deduplicator")
        if dedup and not await dedup.first(getattr(update, "update_id", None)):
            logger.warning("Duplicate Telegram update suppressed: update_id=%s", getattr(update, "update_id", None))
            OBSERVABILITY.emit("duplicate_update", level="WARNING",
                               update_id=getattr(update, "update_id", None))
            raise ApplicationHandlerStop

    application.add_handler(TypeHandler(Update, deduplicate_update), group=-1)

    # Core
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("warnings", warnings_command))
    application.add_handler(CommandHandler("history", history_command))
    application.add_handler(CommandHandler("chatinfo", chatinfo_command))

    # Moderation
    for command, callback in {
        "warn": warn_command, "unwarn": unwarn_command,
        "resetwarnings": resetwarnings_command, "ban": ban_command,
        "unban": unban_command, "mute": mute_command,
        "unmute": unmute_command, "reloadfilters": reloadfilters_command,
    }.items():
        application.add_handler(CommandHandler(command, callback))

    # Settings
    for command, callback in {
        "settings": settings_command, "setwarnlimit": setwarnlimit_command,
        "setmute1": setmute1_command, "setmute2": setmute2_command,
        "setflood": setflood_command, "setfloodmute": setfloodmute_command,
        "setlinkaction": setlinkaction_command, "toggle": toggle_command,
        "addfilter": addfilter_command, "delfilter": delfilter_command,
        "filters": filters_command, "logs": logs_command,
    }.items():
        application.add_handler(CommandHandler(command, callback))

    # Phase 4
    for command, callback in {
        "raidmode": raidmode_command, "setraid": setraid_command,
        "welcome": welcome_command, "stats": stats_command,
    }.items():
        application.add_handler(CommandHandler(command, callback))

    # Phase 5
    for command, callback in {
        "verification": verification_command,
        "setverification": setverification_command,
        "setmaxmsg": setmaxmsg_command,
        "reputation": reputation_command,
    }.items():
        application.add_handler(CommandHandler(command, callback))
    application.add_handler(
        CallbackQueryHandler(verify_callback, pattern=r"^verify:")
    )

    # Phase 6
    for command, callback in {
        "analytics": analytics_command,
        "export": export_command,
        "health": health_command,
    }.items():
        application.add_handler(CommandHandler(command, callback))

    # Phase 15 — Forum Supergroup Engine
    for command, callback in {
        "topics": topics_command,
        "topiccreate": topiccreate_command,
        "topicrename": topicrename_command,
        "topicclose": topicclose_command,
        "topicreopen": topicreopen_command,
        "topicdelete": topicdelete_command,
    }.items():
        application.add_handler(CommandHandler(command, callback))

    # Phase 20 — Final compatibility + production diagnostics
    application.add_handler(CommandHandler("compatibility", compatibility_command))
    application.add_handler(CommandHandler("readiness", readiness_command))


    # H02 — live permission/membership cache invalidation.
    from ghostea.handlers.permission_events import handle_my_chat_member, handle_chat_member
    application.add_handler(
        ChatMemberHandler(handle_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER)
    )
    application.add_handler(
        ChatMemberHandler(handle_chat_member, ChatMemberHandler.CHAT_MEMBER)
    )
    # H04 — edited messages are a distinct Telegram update family. Register
    # before the generic message handler so edited text/captions are evaluated
    # by the same moderation pipeline as new content.
    application.add_handler(
        MessageHandler(filters.UpdateType.EDITED_MESSAGE, check_message)
    )
    # Join events must be registered before the generic message handler.
    application.add_handler(
        MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, handle_new_members)
    )
    application.add_handler(
        MessageHandler(filters.ALL & ~filters.COMMAND, check_message)
    )

    async def error_handler(update, context):
        logger.error("Unhandled bot error: %s", context.error, exc_info=True)

    application.add_error_handler(error_handler)
    return application


def run():
    application = create_application()
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=False,
    )
