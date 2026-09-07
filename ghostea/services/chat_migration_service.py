"""Phase 10: safe Telegram group -> supergroup migration support.

Telegram can migrate a basic group into a supergroup and emit both the old and
new chat ids. Ghostea keeps chat-scoped state keyed by chat_id, so the state
must follow the new Telegram id instead of creating a fresh empty group.

This service deliberately performs a journaled, collision-safe migration.
It never overwrites an existing target chat's data.
"""
import logging
from datetime import datetime, timezone

logger = logging.getLogger("Ghostea")

# Tables whose primary/business identity is rooted in chat_id.
CHAT_SCOPED_TABLES = (
    "ghostea_group_settings",
    "ghostea_warnings",
    "ghostea_warning_history",
    "ghostea_custom_filters",
    "ghostea_moderation_logs",
    "ghostea_join_events",
    "ghostea_raid_events",
    "ghostea_verifications",
    "ghostea_reputation",
    "ghostea_cleanup_runs",
    "ghostea_health_events",
    "ghostea_user_admin_actions",
    "ghostea_security_locks",
    "ghostea_user_directory",
    "ghostea_topic_registry",
    "ghostea_topic_settings",
)


class ChatMigrationService:
    def __init__(self, store, bot=None, permission_service=None):
        self.store = store
        self.bot = bot
        self.permission_service = permission_service

    def attach_runtime(self, bot=None, permission_service=None):
        if bot is not None:
            self.bot = bot
        if permission_service is not None:
            self.permission_service = permission_service

    async def reconcile_telegram_chat(self, chat_id, reason="lifecycle"):
        """Fetch Telegram's current chat identity and reconcile local state.

        Telegram is authoritative for the current chat type, username and forum
        state. This method intentionally does not infer state from migration
        messages alone.
        """
        if self.bot is None:
            raise RuntimeError("migration service bot is not attached")
        from ghostea.services.chat_context import build_chat_context
        from ghostea.services.telegram_resilience import TelegramErrorPolicy

        policy = TelegramErrorPolicy()
        chat = await policy.call_read(
            lambda: self.bot.get_chat(int(chat_id)),
            scope_id=int(chat_id),
        )
        context = build_chat_context(chat)
        if context is None:
            raise RuntimeError(f"unsupported Telegram chat type for {chat_id}")
        if context.chat_type != "supergroup":
            raise RuntimeError(
                f"migration target {chat_id} is not a Telegram supergroup"
            )
        result = await self.reconcile_chat(context, reason=reason)

        # A migration/lifecycle transition invalidates all cached Telegram
        # authorization state. The next operation must observe the new chat.
        if self.permission_service is not None:
            self.permission_service.invalidate_chat(int(chat_id))
        return result, chat

    async def handle_migration(self, old_chat_id, new_chat_id, *, reason="telegram_migration"):
        """Run migration, then verify the new Telegram identity.

        Completion is reported only after local migration and an authoritative
        Telegram chat refresh both succeed. If the refresh is temporarily
        unavailable, the durable migration remains resumable but is not
        represented as a verified lifecycle transition.
        """
        old_chat_id = int(old_chat_id)
        new_chat_id = int(new_chat_id)
        result = await self.migrate(old_chat_id, new_chat_id)
        if self.permission_service is not None:
            self.permission_service.invalidate_chat(old_chat_id)
            self.permission_service.invalidate_chat(new_chat_id)

        reconciled, chat = await self.reconcile_telegram_chat(
            new_chat_id, reason=reason
        )
        # The source id is no longer an operational chat identity after a
        # successful Telegram migration.
        if self.permission_service is not None:
            self.permission_service.invalidate_chat(old_chat_id)
        return {
            "migration": result,
            "reconciliation": reconciled,
            "chat_type": getattr(chat, "type", None),
            "is_forum": bool(getattr(chat, "is_forum", False)),
            "username": getattr(chat, "username", None),
        }

    async def _rows(self, table, chat_id):
        return await self.store._call(
            self.store.db.select,
            table,
            {"chat_id": f"eq.{int(chat_id)}", "limit": "1"},
        )

    async def _migration(self, old_chat_id, new_chat_id):
        rows = await self.store._call(
            self.store.db.select,
            "ghostea_chat_migrations",
            {
                "old_chat_id": f"eq.{int(old_chat_id)}",
                "new_chat_id": f"eq.{int(new_chat_id)}",
                "limit": "1",
            },
        )
        return rows[0] if rows else None

    async def _migrate_registry(self, old_chat_id, new_chat_id):
        old = await self._rows("ghostea_chat_registry", old_chat_id)
        if not old:
            return
        target = await self._rows("ghostea_chat_registry", new_chat_id)
        if target:
            # The target may have been observed just before the migration
            # service ran. Keep the canonical new id and remove only the stale
            # old registry row.
            await self.store._call(
                self.store.db.delete,
                "ghostea_chat_registry",
                {"chat_id": f"eq.{int(old_chat_id)}"},
            )
            return
        # Preserve the last known visibility until the first post-migration
        # update refreshes it from Telegram. The target can subsequently
        # become public/private and touch_chat will update the registry.
        update = {"chat_id": int(new_chat_id), "chat_type": "supergroup"}
        if old[0].get("visibility") in ("public", "private"):
            update["visibility"] = old[0]["visibility"]
        await self.store._call(
            self.store.db.update,
            "ghostea_chat_registry",
            update,
            {"chat_id": f"eq.{int(old_chat_id)}"},
        )

    async def migrate(self, old_chat_id, new_chat_id):
        old_chat_id = int(old_chat_id)
        new_chat_id = int(new_chat_id)
        if old_chat_id == new_chat_id:
            return {"status": "noop", "migrated": []}

        journal = await self._migration(old_chat_id, new_chat_id)
        completed = set((journal or {}).get("completed_tables") or [])

        # A target collision is unsafe to merge implicitly. Journaled retries
        # are allowed to continue only with tables not already migrated.
        for table in CHAT_SCOPED_TABLES:
            # Completed tables are already intentionally present under the new
            # id. Re-checking them would make a journaled retry impossible.
            if table in completed:
                continue
            target = await self._rows(table, new_chat_id)
            if target:
                message = f"target chat already has data in {table}"
                await self._record(old_chat_id, new_chat_id, "blocked", completed, message)
                raise RuntimeError(message)

        await self._record(
            old_chat_id, new_chat_id, "running", completed, None
        )

        if "ghostea_chat_registry" not in completed:
            await self._migrate_registry(old_chat_id, new_chat_id)
            completed.add("ghostea_chat_registry")
            await self._record(old_chat_id, new_chat_id, "running", completed, None)

        for table in CHAT_SCOPED_TABLES:
            if table in completed:
                continue
            source = await self._rows(table, old_chat_id)
            if not source:
                completed.add(table)
                await self._record(old_chat_id, new_chat_id, "running", completed, None)
                continue

            await self.store._call(
                self.store.db.update,
                table,
                {"chat_id": new_chat_id},
                {"chat_id": f"eq.{old_chat_id}"},
            )
            completed.add(table)
            await self._record(old_chat_id, new_chat_id, "running", completed, None)

        await self._record(
            old_chat_id, new_chat_id, "completed", completed, None
        )
        logger.info(
            "Migrated Ghostea chat state %s -> %s (%d tables).",
            old_chat_id, new_chat_id, len(completed),
        )
        return {"status": "completed", "migrated": sorted(completed)}

    async def reconcile_chat(self, chat_context, reason="update"):
        """Reconcile persisted chat identity after migration or lifecycle changes.

        Telegram chat identity can change independently of ordinary messages.
        This method makes the current ChatContext authoritative, while keeping
        forum/topic state consistent with the current chat capabilities.
        """
        if not chat_context or not chat_context.is_supported:
            return {"status": "ignored"}

        chat_id = int(chat_context.chat_id)
        registry = await self._rows("ghostea_chat_registry", chat_id)
        previous = dict(registry[0]) if registry else None

        row = {
            "chat_id": chat_id,
            "chat_type": chat_context.chat_type,
            "title": chat_context.title or None,
            "username": chat_context.username,
            "visibility": chat_context.visibility,
            "is_forum": bool(chat_context.is_forum),
            "last_seen_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        await self.store._call(self.store.db.upsert, "ghostea_chat_registry", row)

        changed = (
            not previous
            or previous.get("chat_type") != row["chat_type"]
            or bool(previous.get("is_forum")) != row["is_forum"]
            or previous.get("username") != row["username"]
            or previous.get("visibility") != row["visibility"]
        )

        # A forum flag disappearing means stored topic rows are no longer
        # operationally reachable. Preserve history but mark them inactive.
        if previous and bool(previous.get("is_forum")) and not row["is_forum"]:
            try:
                await self.store._call(
                    self.store.db.update,
                    "ghostea_topic_registry",
                    {
                        "is_active": False,
                        "is_closed": True,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    },
                    {"chat_id": f"eq.{chat_id}"},
                )
            except Exception:
                logger.exception("Failed to retire stale topic state for %s", chat_id)
                raise

        return {
            "status": "updated" if changed else "unchanged",
            "changed": changed,
            "previous": previous,
            "current": row,
            "reason": reason,
        }

    async def recover_migration(self, old_chat_id, new_chat_id):
        """Retry a previously interrupted migration from its journal."""
        journal = await self._migration(old_chat_id, new_chat_id)
        if not journal:
            return await self.migrate(old_chat_id, new_chat_id)
        if journal.get("status") == "completed":
            return {
                "status": "completed",
                "migrated": sorted(journal.get("completed_tables") or []),
                "recovered": False,
            }
        result = await self.migrate(old_chat_id, new_chat_id)
        result["recovered"] = True
        return result

    async def _record(self, old_chat_id, new_chat_id, status, completed, error):
        payload = {
            "old_chat_id": int(old_chat_id),
            "new_chat_id": int(new_chat_id),
            "status": status,
            "completed_tables": sorted(completed),
            "error": error,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        await self.store._call(
            self.store.db.upsert,
            "ghostea_chat_migrations",
            payload,
        )
