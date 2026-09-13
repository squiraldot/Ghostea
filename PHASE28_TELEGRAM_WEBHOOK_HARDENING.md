# Phase 28 — Telegram Webhook / Update Delivery Hardening

## Goal
Support production-safe Telegram webhook delivery without abandoning the existing polling mode used by current Render testing.

## Implemented
- `GHOSTEA_UPDATE_MODE=polling|webhook`, default `polling`.
- Webhook endpoint reuses the existing Ghostea HTTP server port, avoiding a second listener and preserving Render/VPS/custom topology.
- Exact webhook path matching.
- Telegram `X-Telegram-Bot-Api-Secret-Token` verification using constant-time comparison.
- JSON-only body validation and a 1 MiB request limit.
- Thread-safe handoff into PTB's application update queue on the bot event loop.
- `bot.set_webhook()` with `allowed_updates=Update.ALL_TYPES` and no pending-update discard.
- HTTPS URL, path, query/fragment, and secret validation at startup/setup/readiness.
- Existing polling behavior remains unchanged.
- Setup templates document webhook variables without exposing secrets.

## Deployment strategy
Render remains the current real-time test environment and defaults to polling. VPS/self-hosted and custom deployments are fully developed for webhook mode, but can be tested later when those environments are available.

## Migration
No database migration.
