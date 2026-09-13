"""Phase H02 — live Telegram permission and membership authorization.

Stable chat capabilities answer what Telegram supports.  This service answers
what the bot/user can do *right now*.  Failed Telegram lookups are represented
as lookup failures and are never converted into a permissive answer.
"""
import asyncio
import time
from dataclasses import dataclass
from typing import Optional

from ghostea.services.chat_capabilities import BotPermissions, resolve_bot_permissions
from telegram.constants import ChatMemberStatus
from ghostea.services.telegram_resilience import TelegramErrorPolicy


class PermissionLookupError(RuntimeError):
    """Telegram did not provide a trustworthy permission/membership answer."""


@dataclass(frozen=True)
class PermissionCacheEntry:
    value: object
    expires_at: float


class TelegramPermissionService:
    """Short-TTL live permission cache with update-driven invalidation."""

    def __init__(self, bot, bot_ttl: float = 60.0, member_ttl: float = 30.0):
        self.bot = bot
        self.bot_ttl = float(bot_ttl)
        self.member_ttl = float(member_ttl)
        self._bot_cache: dict[int, PermissionCacheEntry] = {}
        self._member_cache: dict[tuple[int, int], PermissionCacheEntry] = {}
        self._lock = asyncio.Lock()
        self._bot_fetch_locks = {}
        self._member_fetch_locks = {}
        self._max_cache_entries = 20000
        self._bot_generation = {}
        self._member_generation = {}
        self.error_policy = TelegramErrorPolicy()

    @staticmethod
    def _chat_id(chat_or_id) -> int:
        return int(getattr(chat_or_id, "id", chat_or_id))

    async def bot_permissions(self, chat, force: bool = False) -> BotPermissions:
        chat_id = self._chat_id(chat)
        now = time.monotonic()
        async with self._lock:
            entry = self._bot_cache.get(chat_id)
            if not force and entry and entry.expires_at > now:
                return entry.value
            lock = self._bot_fetch_locks.get(chat_id)
            if lock is None:
                lock = asyncio.Lock()
                self._bot_fetch_locks[chat_id] = lock

        async with lock:
            now = time.monotonic()
            async with self._lock:
                entry = self._bot_cache.get(chat_id)
                if not force and entry and entry.expires_at > now:
                    return entry.value
            generation = self._bot_generation.get(chat_id, 0)
            try:
                me = await self.error_policy.call_read(self.bot.get_me, scope_id=chat_id)
                value = await resolve_bot_permissions(chat, me.id, raise_on_error=True)
            except Exception as exc:
                raise PermissionLookupError(
                    f"could_not_verify_bot_permissions:{chat_id}"
                ) from exc

            async with self._lock:
                if self._bot_generation.get(chat_id, 0) == generation:
                    self._bot_cache[chat_id] = PermissionCacheEntry(
                        value, time.monotonic() + self.bot_ttl
                    )
                    self._prune_locked()
            return value

    async def member(self, chat, user_id: int, force: bool = False):
        chat_id = self._chat_id(chat)
        key = (chat_id, int(user_id))
        now = time.monotonic()
        async with self._lock:
            entry = self._member_cache.get(key)
            if not force and entry and entry.expires_at > now:
                return entry.value
            lock = self._member_fetch_locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._member_fetch_locks[key] = lock

        async with lock:
            now = time.monotonic()
            async with self._lock:
                entry = self._member_cache.get(key)
                if not force and entry and entry.expires_at > now:
                    return entry.value
            generation = self._member_generation.get(key, 0)
            try:
                value = await self.error_policy.call_read(
                    lambda: chat.get_member(int(user_id)), scope_id=chat_id
                )
            except Exception as exc:
                raise PermissionLookupError(
                    f"could_not_verify_member:{chat_id}:{user_id}"
                ) from exc

            async with self._lock:
                if self._member_generation.get(key, 0) == generation:
                    self._member_cache[key] = PermissionCacheEntry(
                        value, time.monotonic() + self.member_ttl
                    )
                    self._prune_locked()
            return value

    def _prune_locked(self):
        if len(self._member_cache) + len(self._bot_cache) <= self._max_cache_entries:
            return
        now = time.monotonic()
        expired = [k for k, entry in self._member_cache.items() if entry.expires_at <= now]
        for key in expired[:5000]:
            self._member_cache.pop(key, None)
        expired_bots = [k for k, entry in self._bot_cache.items() if entry.expires_at <= now]
        for key in expired_bots[:1000]:
            self._bot_cache.pop(key, None)
        while len(self._member_cache) + len(self._bot_cache) > self._max_cache_entries:
            if self._member_cache:
                self._member_cache.pop(next(iter(self._member_cache)))
            elif self._bot_cache:
                self._bot_cache.pop(next(iter(self._bot_cache)))
            else:
                break

    async def is_admin(self, chat, user_id: int, force: bool = False) -> bool:
        member = await self.member(chat, user_id, force=force)
        return member.status in (
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
        )

    async def require_bot(self, chat, operation: str) -> BotPermissions:
        """Return live bot permissions or raise a fail-closed error."""
        permissions = await self.bot_permissions(chat)
        if not permissions.is_member:
            raise PermissionLookupError("bot_not_a_member")
        if not permissions.is_admin:
            raise PermissionLookupError("bot_not_an_administrator")

        required = {
            "delete_message": permissions.can_delete_messages,
            "restrict_member": permissions.can_restrict_members,
            "ban_member": permissions.can_ban_members,
            "unban_member": permissions.can_ban_members,
            "set_default_permissions": permissions.can_restrict_members,
            "manage_topics": permissions.can_manage_topics,
        }
        if operation not in required:
            raise KeyError(f"unknown Telegram permission operation: {operation}")
        if not required[operation]:
            raise PermissionError(f"missing_bot_permission:{operation}")
        return permissions

    def invalidate_chat(self, chat_id: int):
        chat_id = int(chat_id)
        self._bot_generation[chat_id] = self._bot_generation.get(chat_id, 0) + 1
        self._bot_cache.pop(chat_id, None)
        for key in [k for k in self._member_cache if k[0] == chat_id]:
            self._member_generation[key] = self._member_generation.get(key, 0) + 1
            self._member_cache.pop(key, None)

    def invalidate_member(self, chat_id: int, user_id: int):
        key = (int(chat_id), int(user_id))
        self._member_generation[key] = self._member_generation.get(key, 0) + 1
        self._member_cache.pop(key, None)

    def clear(self):
        self._bot_cache.clear()
        self._member_cache.clear()
        self._bot_fetch_locks.clear()
        self._member_fetch_locks.clear()
        self._bot_generation.clear()
        self._member_generation.clear()
