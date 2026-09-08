import asyncio
import time
from datetime import datetime, timedelta, timezone

from ghostea.config import (
    DEFAULT_BLOCKED_LINK_ACTION,
    DEFAULT_MAX_WARNINGS,
    DEFAULT_MUTE_MINUTES,
    DEFAULT_SPAM_MESSAGE_LIMIT,
    DEFAULT_SPAM_MUTE_MINUTES,
    DEFAULT_SPAM_WINDOW_SECONDS,
)


class Phase3Store:
    """Persistent settings, warnings, filters, logs, and topic metadata."""

    def __init__(self, db):
        self.db = db
        self._warning_lock = asyncio.Lock()
        self._settings_cache = {}
        self._filters_cache = {}
        self._directory_touch = {}
        self._chat_touch = {}
        self._topic_touch = {}
        self._topic_settings_cache = {}
        self._reputation_locks = {}
        self._cache_locks = {}
        self._cache_ttl = 10.0
        self._directory_touch_ttl = 60.0
        self._chat_touch_ttl = 60.0
        self._topic_touch_ttl = 60.0

    async def _call(self, fn, *args, **kwargs):
        return await asyncio.to_thread(fn, *args, **kwargs)

    def invalidate_group_cache(self, chat_id):
        chat_id = int(chat_id)
        self._settings_cache.pop(chat_id, None)
        for key in list(self._filters_cache):
            if key[0] == chat_id:
                self._filters_cache.pop(key, None)

    def clear_runtime_caches(self):
        """Drop all process-local caches after restart/recovery boundaries.

        Durable state remains in Supabase; these structures are only accelerators
        and throttles. Clearing them prevents stale pre-recovery decisions.
        """
        self._settings_cache.clear()
        self._filters_cache.clear()
        self._directory_touch.clear()
        self._chat_touch.clear()
        self._topic_touch.clear()
        self._topic_settings_cache.clear()
        self._reputation_locks.clear()
        self._cache_locks.clear()

    async def _cache_lock(self, key):
        key = tuple(key) if isinstance(key, (tuple, list)) else key
        lock = self._cache_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._cache_locks[key] = lock
        # Bound idle lock objects; never evict a currently-held lock.
        if len(self._cache_locks) > 20000:
            for old_key, old_lock in list(self._cache_locks.items())[:1000]:
                if not old_lock.locked():
                    self._cache_locks.pop(old_key, None)
        return lock

    def invalidate_chat_cache(self, *chat_ids):
        """Clear transient state after a Telegram chat-id migration."""
        ids = {int(chat_id) for chat_id in chat_ids}
        for chat_id in ids:
            self._settings_cache.pop(chat_id, None)
            self._chat_touch.pop(chat_id, None)
            self._directory_touch.pop(chat_id, None)
            for key in list(self._filters_cache):
                if key[0] == chat_id:
                    self._filters_cache.pop(key, None)
            for key in list(self._topic_touch):
                if key[0] == chat_id:
                    self._topic_touch.pop(key, None)
            for key in list(self._topic_settings_cache):
                if key[0] == chat_id:
                    self._topic_settings_cache.pop(key, None)
            for key in list(self._reputation_locks):
                if key[0] == chat_id:
                    self._reputation_locks.pop(key, None)

    async def list_registered_chats(self, limit=500):
        """Return Ghostea-linked group/supergroup records for authorization flows.

        The registry is the set of chats this bot instance knows about.  It is
        deliberately not treated as an authorization source: callers must
        re-check the Telegram user's current membership/admin status before
        granting an action in a chat.
        """
        limit = max(1, min(int(limit), 500))
        return await self._call(
            self.db.select,
            "ghostea_chat_registry",
            {
                "order": "last_seen_at.desc",
                "limit": str(limit),
            },
        )

    async def touch_chat(self, chat_context):
        """Persist lightweight chat capabilities with a 60-second throttle."""
        if not chat_context or not chat_context.is_supported:
            return None

        chat_id = int(chat_context.chat_id)
        now = time.monotonic()
        previous = self._chat_touch.get(chat_id)
        if previous and now - previous < self._chat_touch_ttl:
            return None

        self._chat_touch[chat_id] = now
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
        try:
            return await self._call(self.db.upsert, "ghostea_chat_registry", row)
        except Exception:
            self._chat_touch.pop(chat_id, None)
            raise


    @staticmethod
    def _topic_event(message):
        """Return (state, name, hidden) for Telegram forum-topic service messages."""
        if not message:
            return None, None, None

        created = getattr(message, "forum_topic_created", None)
        if created is not None:
            return "created", getattr(created, "name", None), False

        edited = getattr(message, "forum_topic_edited", None)
        if edited is not None:
            return "edited", getattr(edited, "name", None), None

        if getattr(message, "forum_topic_closed", None) is not None:
            return "closed", None, None
        if getattr(message, "forum_topic_reopened", None) is not None:
            return "reopened", None, False
        if getattr(message, "general_forum_topic_hidden", None) is not None:
            return "hidden", None, True
        if getattr(message, "general_forum_topic_unhidden", None) is not None:
            return "unhidden", None, False
        # Some PTB versions may expose a deleted-topic service field; keep the
        # parser defensive, but do not depend on it because the Bot API does
        # not promise a dedicated topic-deletion update.
        if getattr(message, "forum_topic_deleted", None) is not None:
            return "deleted", None, None
        return None, None, None

    async def touch_topic(self, chat_context, message=None):
        """Persist forum-topic metadata with a throttled activity update.

        Topic rows are keyed by (chat_id, topic_id). This method is intentionally
        a no-op for normal groups, non-forum supergroups, and messages without a
        concrete topic id.
        """
        if not chat_context:
            return None
        topic_capable = bool(
            getattr(chat_context, "is_topic_capable", getattr(chat_context, "is_forum", False))
        )
        if not topic_capable or chat_context.topic_id is None:
            return None

        chat_id = int(chat_context.chat_id)
        topic_id = int(chat_context.topic_id)
        event, event_name, event_hidden = self._topic_event(message)
        key = (chat_id, topic_id)
        now = time.monotonic()

        # Service events must always be persisted; ordinary topic activity is
        # throttled to avoid a database write for every message.
        force = event is not None
        previous = self._topic_touch.get(key)
        if not force and previous and now - previous < self._topic_touch_ttl:
            return None

        self._topic_touch[key] = now
        row = {
            "chat_id": chat_id,
            "topic_id": topic_id,
            "name": event_name,
            "is_active": True,
            "is_closed": False,
            "is_hidden": False,
            "last_seen_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        # Preserve existing lifecycle metadata unless the event explicitly
        # changes it. This matters for close/reopen/edit events: an edited
        # topic must not accidentally reopen a closed topic, and a close event
        # must not erase the stored topic name.
        try:
            existing = await self._call(
                self.db.select,
                "ghostea_topic_registry",
                {
                    "chat_id": f"eq.{chat_id}",
                    "topic_id": f"eq.{topic_id}",
                    "limit": "1",
                },
            )
            if existing:
                current = existing[0]
                row["name"] = current.get("name")
                row["is_active"] = bool(current.get("is_active", True))
                row["is_closed"] = bool(current.get("is_closed", False))
                row["is_hidden"] = bool(current.get("is_hidden", False))
        except Exception:
            # A missing Phase 3 table should be visible to deployment
            # diagnostics rather than silently corrupting moderation state.
            self._topic_touch.pop(key, None)
            raise

        if event in ("created", "edited") and event_name:
            row["name"] = event_name
        if event_hidden is not None:
            row["is_hidden"] = bool(event_hidden)
        if event == "closed":
            row["is_closed"] = True
        elif event == "reopened":
            row["is_closed"] = False
            row["is_hidden"] = False
            row["is_active"] = True
        elif event == "hidden":
            row["is_hidden"] = True
            row["is_closed"] = True
        elif event == "unhidden":
            row["is_hidden"] = False
            row["is_closed"] = False
            row["is_active"] = True
        elif event == "deleted":
            row["is_active"] = False
            row["is_closed"] = True
            row["is_hidden"] = False
        elif event == "created":
            row["is_active"] = True
            row["is_closed"] = False
            row["is_hidden"] = False

        try:
            return await self._call(
                self.db.upsert, "ghostea_topic_registry", row
            )
        except Exception:
            self._topic_touch.pop(key, None)
            raise

    async def upsert_topic_lifecycle(self, chat_id, topic_id, name=None, is_active=True, is_closed=False, is_hidden=False):
        """Persist an explicit forum topic lifecycle transition."""
        now = datetime.now(timezone.utc).isoformat()
        payload = {
            "chat_id": int(chat_id),
            "topic_id": int(topic_id),
            "name": name,
            "is_active": bool(is_active),
            "is_closed": bool(is_closed),
            "is_hidden": bool(is_hidden),
            "last_seen_at": now,
            "updated_at": now,
        }
        result = await self._call(
            self.db.upsert, "ghostea_topic_registry", payload
        )
        self._topic_touch.pop((int(chat_id), int(topic_id)), None)
        return result[0] if result else payload

    async def get_topic(self, chat_id, topic_id):
        rows = await self._call(
            self.db.select,
            "ghostea_topic_registry",
            {
                "chat_id": f"eq.{int(chat_id)}",
                "topic_id": f"eq.{int(topic_id)}",
                "limit": "1",
            },
        )
        return rows[0] if rows else None

    async def list_topics(self, chat_id, include_inactive=False, limit=200):
        limit = max(1, min(int(limit), 500))
        query = {
            "chat_id": f"eq.{int(chat_id)}",
            "order": "updated_at.desc",
            "limit": str(limit),
        }
        if not include_inactive:
            query["is_active"] = "eq.true"
        return await self._call(
            self.db.select, "ghostea_topic_registry", query
        )

    # Topic overrides intentionally mirror only settings that are meaningful to
    # message moderation. Chat-wide lifecycle controls (welcome, verification,
    # anti-raid, warning decay, etc.) remain group-scoped so users cannot evade
    # moderation by moving between topics.
    TOPIC_OVERRIDE_SCHEMA = {
        "abuse_filter_enabled": "bool",
        "spam_filter_enabled": "bool",
        "link_filter_enabled": "bool",
        "flood_protection_enabled": "bool",
        "flood_window_seconds": "positive_int",
        "flood_message_limit": "positive_int",
        "flood_mute_minutes": "positive_int",
        "blocked_link_action": "action",
        "repeated_message_window_seconds": "positive_int",
        "repeated_message_limit": "positive_int",
        "mention_spam_limit": "positive_int",
        "max_message_length": "positive_int",
    }

    @classmethod
    def _validate_topic_overrides(cls, changes):
        """Validate and sanitize a topic override payload.

        Unknown keys and group identity/timestamp fields are rejected instead
        of being persisted. This keeps topic settings a strict overlay on the
        group settings schema.
        """
        if not isinstance(changes, dict):
            raise ValueError("topic settings must be an object")

        clean = {}
        for key, value in changes.items():
            if key not in cls.TOPIC_OVERRIDE_SCHEMA:
                raise ValueError(f"unsupported topic setting: {key}")

            kind = cls.TOPIC_OVERRIDE_SCHEMA[key]
            if kind == "bool":
                if not isinstance(value, bool):
                    raise ValueError(f"{key} must be boolean")
                clean[key] = value
            elif kind == "positive_int":
                if isinstance(value, bool):
                    raise ValueError(f"{key} must be an integer")
                try:
                    number = int(value)
                except (TypeError, ValueError):
                    raise ValueError(f"{key} must be an integer")
                if number < 1 or number > 10080:
                    raise ValueError(f"{key} is out of range")
                clean[key] = number
            elif kind == "action":
                if value not in ("delete", "warn", "mute", "ban"):
                    raise ValueError(f"{key} has an invalid action")
                clean[key] = value
        return clean

    def _invalidate_topic_settings_cache(self, chat_id, topic_id):
        self._topic_settings_cache.pop((int(chat_id), int(topic_id)), None)

    async def get_topic_settings(self, chat_id, topic_id):
        key = (int(chat_id), int(topic_id))
        now = time.monotonic()
        cached = self._topic_settings_cache.get(key)
        if cached and cached[0] > now:
            return dict(cached[1])

        rows = await self._call(
            self.db.select,
            "ghostea_topic_settings",
            {
                "chat_id": f"eq.{key[0]}",
                "topic_id": f"eq.{key[1]}",
                "limit": "1",
            },
        )
        value = dict(rows[0].get("settings") or {}) if rows else {}
        self._topic_settings_cache[key] = (now + self._cache_ttl, value)
        return dict(value)

    async def update_topic_settings(self, chat_id, topic_id, changes):
        """Merge validated topic overrides into the existing overlay."""
        clean = self._validate_topic_overrides(changes)
        if not clean:
            return await self.get_topic_settings(chat_id, topic_id)

        current = await self.get_topic_settings(chat_id, topic_id)
        current.update(clean)
        rows = await self._call(
            self.db.upsert,
            "ghostea_topic_settings",
            {
                "chat_id": int(chat_id),
                "topic_id": int(topic_id),
                "settings": current,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        self._topic_settings_cache[(int(chat_id), int(topic_id))] = (
            time.monotonic() + self._cache_ttl,
            dict(current),
        )
        return rows[0] if rows else dict(current)

    async def clear_topic_settings(self, chat_id, topic_id, keys=None):
        """Clear selected overrides, or the entire topic overlay."""
        key = (int(chat_id), int(topic_id))
        current = await self.get_topic_settings(*key)
        if keys is None:
            new_settings = {}
        else:
            requested = list(keys) if not isinstance(keys, str) else [keys]
            unknown = [item for item in requested if item not in self.TOPIC_OVERRIDE_SCHEMA]
            if unknown:
                raise ValueError(f"unsupported topic setting: {unknown[0]}")
            new_settings = {k: v for k, v in current.items() if k not in requested}

        if new_settings:
            await self._call(
                self.db.update,
                "ghostea_topic_settings",
                {"settings": new_settings, "updated_at": datetime.now(timezone.utc).isoformat()},
                {"chat_id": f"eq.{key[0]}", "topic_id": f"eq.{key[1]}"},
            )
        else:
            await self._call(
                self.db.delete,
                "ghostea_topic_settings",
                {"chat_id": f"eq.{key[0]}", "topic_id": f"eq.{key[1]}"},
            )
        self._topic_settings_cache.pop(key, None)
        return new_settings

    async def get_effective_settings(self, chat_id, topic_id=None):
        """Resolve settings as Topic Override -> Group Setting -> Default.

        ``topic_id=None`` is deliberately a fast path for normal groups and
        non-forum supergroups. For forum messages, only the validated topic
        overlay is applied; all other controls stay chat-wide.
        """
        base = dict(await self.get_settings(chat_id))
        if topic_id is None:
            return base

        overrides = await self.get_topic_settings(chat_id, topic_id)
        for key, value in overrides.items():
            # Defensive guard for rows written by an older/newer deployment.
            if key in self.TOPIC_OVERRIDE_SCHEMA:
                base[key] = value
        return base

    async def touch_user(self, chat_id, user_id):
        """Keep a lightweight observed-user directory without writing per message."""
        key = (int(chat_id), int(user_id))
        now = time.monotonic()
        last = self._directory_touch.get(key, 0.0)
        if now - last < self._directory_touch_ttl:
            return
        self._directory_touch[key] = now
        if len(self._directory_touch) > 100000:
            cutoff = now - 3600.0
            stale = [k for k, seen in self._directory_touch.items() if seen < cutoff]
            for stale_key in stale[:10000]:
                self._directory_touch.pop(stale_key, None)
        try:
            await self._call(
                self.db.upsert,
                "ghostea_user_directory",
                {
                    "chat_id": int(chat_id),
                    "user_id": int(user_id),
                    "last_activity": datetime.now(timezone.utc).isoformat(),
                },
            )
        except Exception:
            # Directory indexing must never break moderation.
            self._directory_touch.pop(key, None)

    async def get_settings(self, chat_id):
        chat_id = int(chat_id)
        now = time.monotonic()
        cached = self._settings_cache.get(chat_id)
        if cached and cached[0] > now:
            return dict(cached[1])

        lock = await self._cache_lock(("settings", chat_id))
        async with lock:
            now = time.monotonic()
            cached = self._settings_cache.get(chat_id)
            if cached and cached[0] > now:
                return dict(cached[1])

            rows = await self._call(
                self.db.select,
                "ghostea_group_settings",
                {"chat_id": f"eq.{chat_id}", "limit": "1"},
            )

            if rows:
                value = dict(rows[0])
                self._settings_cache[chat_id] = (time.monotonic() + self._cache_ttl, value)
                return value

            defaults = {
                "chat_id": chat_id,
                "max_warnings": DEFAULT_MAX_WARNINGS,
                "mute1_minutes": DEFAULT_MUTE_MINUTES[1],
                "mute2_minutes": DEFAULT_MUTE_MINUTES[2],
                "flood_window_seconds": DEFAULT_SPAM_WINDOW_SECONDS,
                "flood_message_limit": DEFAULT_SPAM_MESSAGE_LIMIT,
                "flood_mute_minutes": DEFAULT_SPAM_MUTE_MINUTES,
                "blocked_link_action": DEFAULT_BLOCKED_LINK_ACTION,
                "abuse_filter_enabled": True,
                "spam_filter_enabled": True,
                "link_filter_enabled": True,
                "flood_protection_enabled": True,
                "welcome_enabled": True,
                "antiraid_enabled": True,
                "antiraid_join_limit": 8,
                "antiraid_window_seconds": 20,
                "antiraid_lock_minutes": 10,
                "auto_cleanup_enabled": False,
                "verification_enabled": True,
                "verification_timeout_seconds": 120,
                "min_account_age_days": 0,
                "new_member_restriction_minutes": 0,
                "repeated_message_window_seconds": 60,
                "repeated_message_limit": 3,
                "mention_spam_limit": 6,
                "max_message_length": 4000,
                "warning_decay_enabled": True,
                "warning_decay_days": 30,
                "cleanup_max_age_days": 30,
            }

            await self._call(self.db.upsert, "ghostea_group_settings", defaults)
            self._settings_cache[chat_id] = (time.monotonic() + self._cache_ttl, dict(defaults))
            return defaults

    async def update_settings(self, chat_id, changes):
        changes = dict(changes)
        changes["updated_at"] = datetime.now(timezone.utc).isoformat()
        rows = await self._call(
            self.db.update,
            "ghostea_group_settings",
            changes,
            {"chat_id": f"eq.{chat_id}"},
        )
        self.invalidate_group_cache(chat_id)
        return rows[0] if rows else await self.get_settings(chat_id)

    async def _warning_policy(self, chat_id):
        settings = await self.get_settings(chat_id)
        enabled = bool(settings.get("warning_decay_enabled", True))
        days = max(1, int(settings.get("warning_decay_days", 30)))
        return enabled, days

    async def get_warning_count(self, chat_id, user_id):
        rows = await self._call(
            self.db.select,
            "ghostea_warnings",
            {
                "chat_id": f"eq.{chat_id}",
                "user_id": f"eq.{user_id}",
                "limit": "1",
            },
        )
        current = rows[0] if rows else None

        decay_enabled, decay_days = await self._warning_policy(chat_id)
        if not decay_enabled:
            return int(current["count"]) if current else 0

        cutoff_dt = datetime.now(timezone.utc) - timedelta(days=decay_days)
        cutoff = cutoff_dt.isoformat()
        # Most reads can use the compact count row without touching warning
        # history. Recalculate only when that row has aged past the decay
        # window or does not exist.
        if current:
            updated = self._parse_datetime(current.get("updated_at"))
            if updated and updated >= cutoff_dt:
                return int(current.get("count", 0))

        recent = await self._call(
            self.db.select,
            "ghostea_warning_history",
            {
                "chat_id": f"eq.{chat_id}",
                "user_id": f"eq.{user_id}",
                "active": "eq.true",
                "created_at": f"gte.{cutoff}",
                "select": "id,created_at",
                "order": "created_at.desc",
                "limit": "1000",
            },
        )
        count = len(recent)
        newest = recent[0].get("created_at") if recent else None
        await self._call(
            self.db.upsert,
            "ghostea_warnings",
            {
                "chat_id": chat_id,
                "user_id": user_id,
                "count": count,
                # Track the newest active warning, not the recalculation time,
                # so the next individual warning can decay naturally.
                "updated_at": newest or datetime.now(timezone.utc).isoformat(),
            },
        )
        return count

    @staticmethod
    def _parse_datetime(value):
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
        except (TypeError, ValueError):
            return None

    async def add_warning(self, chat_id, user_id, reason, source):
        # Serialize increments within this bot process so two simultaneous
        # detections do not overwrite the same warning count.
        async with self._warning_lock:
            count = await self.get_warning_count(chat_id, user_id) + 1

            await self._call(
                self.db.upsert,
                "ghostea_warnings",
                {
                    "chat_id": chat_id,
                    "user_id": user_id,
                    "count": count,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            await self._call(
                self.db.insert,
                "ghostea_warning_history",
                {
                    "chat_id": chat_id,
                    "user_id": user_id,
                    "reason": reason,
                    "source": source,
                    "active": True,
                },
            )
            await self.log(
                chat_id, user_id, "WARN", reason,
                f"warning_count={count};source={source}",
            )
            return count

    async def remove_warning(self, chat_id, user_id):
        decay_enabled, decay_days = await self._warning_policy(chat_id)
        query = {
            "chat_id": f"eq.{chat_id}",
            "user_id": f"eq.{user_id}",
            "active": "eq.true",
            "order": "created_at.desc",
            "limit": "1",
        }
        if decay_enabled:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=decay_days)).isoformat()
            query["created_at"] = f"gte.{cutoff}"
        rows = await self._call(self.db.select, "ghostea_warning_history", query)
        if rows:
            await self._call(
                self.db.update, "ghostea_warning_history", {"active": False},
                {"id": f"eq.{rows[0]['id']}"},
            )
        count = await self.get_warning_count(chat_id, user_id)
        await self._call(
            self.db.upsert,
            "ghostea_warnings",
            {"chat_id": chat_id, "user_id": user_id, "count": count, "updated_at": datetime.now(timezone.utc).isoformat()},
        )
        return count

    async def reset_warnings(self, chat_id, user_id):
        await self._call(
            self.db.update, "ghostea_warning_history", {"active": False},
            {"chat_id": f"eq.{chat_id}", "user_id": f"eq.{user_id}", "active": "eq.true"},
        )
        await self._call(
            self.db.upsert,
            "ghostea_warnings",
            {"chat_id": chat_id, "user_id": user_id, "count": 0, "updated_at": datetime.now(timezone.utc).isoformat()},
        )
        await self.log(chat_id, user_id, "RESET_WARNINGS", "Admin reset", "")

    async def get_history(self, chat_id, user_id, limit=10):
        return await self._call(
            self.db.select,
            "ghostea_warning_history",
            {
                "chat_id": f"eq.{chat_id}",
                "user_id": f"eq.{user_id}",
                "order": "created_at.desc",
                "limit": str(limit),
            },
        )

    async def add_custom_filter(self, chat_id, filter_type, value):
        result = await self._call(
            self.db.upsert,
            "ghostea_custom_filters",
            {
                "chat_id": chat_id,
                "filter_type": filter_type,
                "value": value,
                "enabled": True,
            },
        )
        self.invalidate_group_cache(chat_id)
        return result

    async def remove_custom_filter(self, chat_id, filter_type, value):
        result = await self._call(
            self.db.delete,
            "ghostea_custom_filters",
            {
                "chat_id": f"eq.{chat_id}",
                "filter_type": f"eq.{filter_type}",
                "value": f"eq.{value}",
            },
        )
        self.invalidate_group_cache(chat_id)
        return result

    async def remove_custom_filter_by_id(self, chat_id, filter_id):
        result = await self._call(
            self.db.delete,
            "ghostea_custom_filters",
            {"chat_id": f"eq.{chat_id}", "id": f"eq.{int(filter_id)}"},
        )
        self.invalidate_group_cache(chat_id)
        return result

    async def get_custom_filters(self, chat_id, filter_type=None):
        key = (int(chat_id), filter_type or "*")
        now = time.monotonic()
        cached = self._filters_cache.get(key)
        if cached and cached[0] > now:
            return list(cached[1])

        query = {
            "chat_id": f"eq.{chat_id}",
            "enabled": "eq.true",
            "order": "created_at.asc",
        }
        if filter_type:
            query["filter_type"] = f"eq.{filter_type}"

        rows = await self._call(
            self.db.select,
            "ghostea_custom_filters",
            query,
        )
        self._filters_cache[key] = (time.monotonic() + self._cache_ttl, list(rows))
        return rows

    async def log(
        self,
        chat_id,
        user_id,
        action,
        reason="",
        details="",
        topic_id=None,
    ):
        """Persist a moderation event with optional forum-topic context.

        Warnings, reputation, and administrative state remain chat-wide.
        Moderation logs are the historical event stream, so a nullable
        topic_id records where a forum event occurred without changing the
        identity/scope of the underlying user.
        """
        topic_id = int(topic_id) if topic_id is not None else None
        result = await self._call(
            self.db.insert,
            "ghostea_moderation_logs",
            {
                "chat_id": chat_id,
                "user_id": user_id,
                "topic_id": topic_id,
                "action": action,
                "reason": reason,
                "details": details,
            },
        )
        return result

    async def recent_logs(self, chat_id, limit=20, topic_id=None):
        query = {
            "chat_id": f"eq.{chat_id}",
            "order": "created_at.desc",
            "limit": str(max(1, min(int(limit), 200))),
        }
        if topic_id is not None:
            query["topic_id"] = f"eq.{int(topic_id)}"
        return await self._call(
            self.db.select,
            "ghostea_moderation_logs",
            query,
        )

    async def record_join(self, chat_id, user_id):
        result = await self._call(
            self.db.insert,
            "ghostea_join_events",
            {"chat_id": chat_id, "user_id": user_id},
        )
        await self.touch_user(chat_id, user_id)
        return result

    async def log_raid_event(self, chat_id, action, details=""):
        return await self._call(
            self.db.insert,
            "ghostea_raid_events",
            {"chat_id": chat_id, "action": action, "details": details},
        )

    async def get_stats(self, chat_id):
        try:
            warnings = await self._call(
                self.db.count, "ghostea_warning_history",
                {"chat_id": f"eq.{chat_id}"},
            )
            actions = await self._call(
                self.db.count, "ghostea_moderation_logs",
                {"chat_id": f"eq.{chat_id}"},
            )
            joins = await self._call(
                self.db.count, "ghostea_join_events",
                {"chat_id": f"eq.{chat_id}"},
            )
            return {"warnings": warnings, "actions": actions, "joins": joins}
        except Exception:
            # Fallback for older PostgREST configurations without count support.
            warnings = await self._call(self.db.select, "ghostea_warning_history", {"chat_id": f"eq.{chat_id}", "select": "id", "limit": "1000"})
            actions = await self._call(self.db.select, "ghostea_moderation_logs", {"chat_id": f"eq.{chat_id}", "select": "id", "limit": "1000"})
            joins = await self._call(self.db.select, "ghostea_join_events", {"chat_id": f"eq.{chat_id}", "select": "id", "limit": "1000"})
            return {"warnings": len(warnings), "actions": len(actions), "joins": len(joins), "partial": True}


    async def save_verification(self, chat_id, user_id, token, expires_at):
        return await self._call(
            self.db.upsert,
            "ghostea_verifications",
            {
                "chat_id": chat_id,
                "user_id": user_id,
                "token": token,
                "expires_at": expires_at,
                "verified": False,
            },
        )

    async def get_verification(self, chat_id, user_id):
        rows = await self._call(
            self.db.select,
            "ghostea_verifications",
            {
                "chat_id": f"eq.{chat_id}",
                "user_id": f"eq.{user_id}",
                "limit": "1",
            },
        )
        return rows[0] if rows else None

    async def verify_user(self, chat_id, user_id):
        return await self._call(
            self.db.update,
            "ghostea_verifications",
            {"verified": True},
            {"chat_id": f"eq.{chat_id}", "user_id": f"eq.{user_id}"},
        )

    async def delete_verification(self, chat_id, user_id):
        return await self._call(
            self.db.delete,
            "ghostea_verifications",
            {
                "chat_id": f"eq.{chat_id}",
                "user_id": f"eq.{user_id}",
            },
        )


    async def upsert_security_lock(
        self, chat_id, lock_type, expires_at, original_permissions
    ):
        return await self._call(
            self.db.upsert,
            "ghostea_security_locks",
            {
                "chat_id": chat_id,
                "lock_type": lock_type,
                "expires_at": expires_at,
                "original_permissions": original_permissions or {},
            },
        )

    async def get_security_lock(self, chat_id, lock_type):
        rows = await self._call(
            self.db.select,
            "ghostea_security_locks",
            {
                "chat_id": f"eq.{chat_id}",
                "lock_type": f"eq.{lock_type}",
                "limit": "1",
            },
        )
        return rows[0] if rows else None

    async def get_active_security_locks(self):
        return await self._call(
            self.db.select,
            "ghostea_security_locks",
            {
                "order": "expires_at.asc",
                "limit": "200",
            },
        )

    async def delete_security_lock(self, chat_id, lock_type):
        return await self._call(
            self.db.delete,
            "ghostea_security_locks",
            {
                "chat_id": f"eq.{chat_id}",
                "lock_type": f"eq.{lock_type}",
            },
        )

    async def get_expired_verifications(self, now_iso, limit=100):
        return await self._call(
            self.db.select,
            "ghostea_verifications",
            {
                "verified": "eq.false",
                "expires_at": f"lt.{now_iso}",
                "order": "expires_at.asc",
                "limit": str(max(1, min(int(limit), 500))),
            },
        )

    async def get_user_directory(self, chat_id, limit=100):
        """Return observed users with bounded, index-friendly enrichment queries."""
        limit = max(1, min(int(limit), 500))
        try:
            directory = await self._call(
                self.db.select,
                "ghostea_user_directory",
                {
                    "chat_id": f"eq.{chat_id}",
                    "order": "last_activity.desc",
                    "limit": str(limit),
                },
            )
            ids = [int(row["user_id"]) for row in directory if row.get("user_id") is not None]
            # A migrated/new directory can exist but still be empty. Fall
            # through to legacy activity sources instead of showing a false
            # "No users recorded yet" state.
            if not ids:
                raise RuntimeError("user_directory_empty")
            id_filter = "in.(" + ",".join(str(x) for x in ids) + ")"

            warnings = await self._call(
                self.db.select,
                "ghostea_warnings",
                {
                    "chat_id": f"eq.{chat_id}",
                    "user_id": id_filter,
                    "select": "user_id,count",
                    "limit": str(limit),
                },
            )
            reps = await self._call(
                self.db.select,
                "ghostea_reputation",
                {
                    "chat_id": f"eq.{chat_id}",
                    "user_id": id_filter,
                    "select": "user_id,score",
                    "limit": str(limit),
                },
            )
            # Action counts are derived from logs only for the bounded set of
            # users displayed on this page. This avoids a full-table GROUP BY.
            logs = await self._call(
                self.db.select,
                "ghostea_moderation_logs",
                {
                    "chat_id": f"eq.{chat_id}",
                    "user_id": id_filter,
                    "select": "user_id,id",
                    "limit": "1000",
                },
            )
            warning_map = {str(row["user_id"]): int(row.get("count", 0)) for row in warnings}
            rep_map = {str(row["user_id"]): int(row.get("score", 0)) for row in reps}
            action_map = {}
            for row in logs:
                key = str(row.get("user_id"))
                action_map[key] = action_map.get(key, 0) + 1

            result = []
            for row in directory:
                key = str(row["user_id"])
                result.append({
                    "chat_id": int(chat_id),
                    "user_id": int(row["user_id"]),
                    "first_seen_at": row.get("first_seen_at"),
                    "last_activity": row.get("last_activity"),
                    "warnings": warning_map.get(key, 0),
                    "actions": action_map.get(key, 0),
                    "reputation": rep_map.get(key, 0),
                })
            return result
        except Exception:
            # Backward-compatible fallback until the Phase 14 directory table
            # exists. Keep the fallback bounded so it cannot fan out endlessly.
            warnings = await self._call(
                self.db.select,
                "ghostea_warning_history",
                {"chat_id": f"eq.{chat_id}", "order": "created_at.desc", "limit": "200"},
            )
            logs = await self._call(
                self.db.select,
                "ghostea_moderation_logs",
                {"chat_id": f"eq.{chat_id}", "order": "created_at.desc", "limit": "200"},
            )
            joins = await self._call(
                self.db.select,
                "ghostea_join_events",
                {"chat_id": f"eq.{chat_id}", "order": "joined_at.desc", "limit": "200"},
            )
            reps = await self._call(
                self.db.select,
                "ghostea_reputation",
                {"chat_id": f"eq.{chat_id}", "select": "user_id,score", "limit": "500"},
            )
            users = {}
            def ensure(uid, ts=None):
                item = users.setdefault(str(uid), {
                    "user_id": int(uid), "warnings": 0, "actions": 0,
                    "reputation": 0, "last_activity": ts,
                })
                if ts and (not item["last_activity"] or str(ts) > str(item["last_activity"])):
                    item["last_activity"] = ts
                return item
            for row in warnings:
                uid = row.get("user_id")
                if uid is not None:
                    ensure(uid, row.get("created_at"))["warnings"] += 1
            for row in logs:
                uid = row.get("user_id")
                if uid is not None:
                    ensure(uid, row.get("created_at"))["actions"] += 1
            for row in joins:
                uid = row.get("user_id")
                if uid is not None:
                    ensure(uid, row.get("joined_at"))
            for row in reps:
                uid = row.get("user_id")
                if uid is not None:
                    ensure(uid)["reputation"] = int(row.get("score", 0) or 0)
            return sorted(
                users.values(),
                key=lambda x: (x["last_activity"] or "", x["warnings"], x["actions"]),
                reverse=True,
            )[:limit]

    async def get_reputation(self, chat_id, user_id):
        rows = await self._call(
            self.db.select,
            "ghostea_reputation",
            {
                "chat_id": f"eq.{chat_id}",
                "user_id": f"eq.{user_id}",
                "limit": "1",
            },
        )
        if rows:
            return rows[0]
        default = {
            "chat_id": chat_id,
            "user_id": user_id,
            "score": 0,
            "positive_actions": 0,
            "negative_actions": 0,
        }
        return default

    async def change_reputation(self, chat_id, user_id, delta):
        key = (int(chat_id), int(user_id))
        lock = self._reputation_locks.setdefault(key, asyncio.Lock())
        async with lock:
            current = await self.get_reputation(chat_id, user_id)
            score = int(current["score"]) + int(delta)
            positive = int(current["positive_actions"]) + (1 if delta > 0 else 0)
            negative = int(current["negative_actions"]) + (1 if delta < 0 else 0)

            await self._call(
                self.db.upsert,
                "ghostea_reputation",
                {
                    "chat_id": chat_id,
                    "user_id": user_id,
                    "score": score,
                    "positive_actions": positive,
                    "negative_actions": negative,
                },
            )
            return score

    async def record_cleanup(self, chat_id, cutoff_at, deleted_count):
        return await self._call(
            self.db.insert,
            "ghostea_cleanup_runs",
            {
                "chat_id": chat_id,
                "cutoff_at": cutoff_at,
                "deleted_count": deleted_count,
            },
        )


    async def get_analytics(self, chat_id, since_iso, topic_id=None):
        """Return chat analytics, optionally scoped to one forum topic.

        Warning history and joins are intentionally always chat-wide because
        those records represent member state. Only the moderation event stream
        is filtered by topic.
        """
        warnings = await self._call(
            self.db.select,
            "ghostea_warning_history",
            {"chat_id": f"eq.{chat_id}", "created_at": f"gte.{since_iso}",
             "select": "id,user_id,reason,source,created_at",
             "order": "created_at.desc", "limit": "1000"},
        )
        log_query = {
            "chat_id": f"eq.{chat_id}", "created_at": f"gte.{since_iso}",
            "select": "id,user_id,topic_id,action,reason,created_at,details",
            "order": "created_at.desc", "limit": "1000",
        }
        if topic_id is not None:
            log_query["topic_id"] = f"eq.{int(topic_id)}"
        logs = await self._call(
            self.db.select,
            "ghostea_moderation_logs",
            log_query,
        )
        joins = await self._call(
            self.db.select,
            "ghostea_join_events",
            {"chat_id": f"eq.{chat_id}", "joined_at": f"gte.{since_iso}",
             "select": "id,user_id,joined_at",
             "order": "joined_at.desc", "limit": "1000"},
        )
        return {"warnings": warnings, "logs": logs, "joins": joins,
                "topic_id": int(topic_id) if topic_id is not None else None}

    async def log_health(self, status, details="", chat_id=None):
        return await self._call(
            self.db.insert, "ghostea_health_events",
            {"chat_id": chat_id, "status": status, "details": details},
        )


    async def get_user_profile(self, chat_id, user_id, log_limit=100):
        warnings = await self.get_warning_count(chat_id, user_id)
        history = await self.get_history(chat_id, user_id, limit=log_limit)
        reputation = await self.get_reputation(chat_id, user_id)
        logs = await self._call(
            self.db.select,
            "ghostea_moderation_logs",
            {
                "chat_id": f"eq.{chat_id}",
                "user_id": f"eq.{user_id}",
                "order": "created_at.desc",
                "limit": str(log_limit),
            },
        )
        return {
            "chat_id": chat_id,
            "user_id": user_id,
            "warnings": warnings,
            "warning_history": history,
            "reputation": reputation,
            "moderation_logs": logs,
        }

    async def log_user_admin_action(
        self, chat_id, target_user_id, admin_user_id, action, details=""
    ):
        return await self._call(
            self.db.insert,
            "ghostea_user_admin_actions",
            {
                "chat_id": chat_id,
                "target_user_id": target_user_id,
                "admin_user_id": admin_user_id,
                "action": action,
                "details": details,
            },
        )

    async def recent_user_admin_actions(
        self, chat_id, target_user_id, limit=100
    ):
        return await self._call(
            self.db.select,
            "ghostea_user_admin_actions",
            {
                "chat_id": f"eq.{chat_id}",
                "target_user_id": f"eq.{target_user_id}",
                "order": "created_at.desc",
                "limit": str(limit),
            },
        )

