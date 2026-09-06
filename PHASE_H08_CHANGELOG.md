# Phase H08 Changelog

- Added authoritative post-migration Telegram reconciliation.
- Added resumable migration handling through `handle_migration`.
- Invalidated old/new Telegram permission caches during lifecycle transitions.
- Reconciled group/supergroup identity on `my_chat_member`.
- Preserved durable migration state when Telegram refresh is temporarily unavailable.
- Added H08 regression coverage.
