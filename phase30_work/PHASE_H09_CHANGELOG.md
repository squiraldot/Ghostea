# Phase H09 Changelog

- Added centralized `StateRecoveryService` startup coordinator.
- Added explicit runtime-cache clearing before durable recovery.
- Added protection-service runtime-state reset.
- Hardened verification expiry so transient Telegram failures preserve the
  durable verification record for a later retry.
- Hardened anti-raid expiry so failed restoration preserves the durable lock.
- Added H09 regression coverage.
- No new user-facing features.
- No new environment variables.
- No database migration required.
