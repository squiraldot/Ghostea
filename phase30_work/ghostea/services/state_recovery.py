"""Phase H09 — durable state recovery and consistency coordinator.

Durable Ghostea state lives in Supabase. Telegram is authoritative for
Telegram-owned state (membership, permissions, current chat state). Process-local
caches and anti-spam windows are intentionally disposable and are cleared at
recovery boundaries.
"""
import logging

logger = logging.getLogger("Ghostea")


class StateRecoveryService:
    def __init__(self, store, protection, security, permission_service=None):
        self.store = store
        self.protection = protection
        self.security = security
        self.permission_service = permission_service

    async def recover(self):
        """Perform a safe startup recovery without inventing Telegram state."""
        # Runtime caches are not durable truth. Clear them before reading
        # persisted records so recovery cannot use stale in-process decisions.
        self.store.clear_runtime_caches()
        if hasattr(self.protection, "clear_runtime_state"):
            self.protection.clear_runtime_state()
        if self.permission_service is not None:
            self.permission_service.clear()

        await self.security.start()
        return {
            "runtime_caches_cleared": True,
            "security_recovered": True,
        }
