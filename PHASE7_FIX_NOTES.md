# Phase 7 Fix — Upload Authorization + Publishing Reliability

## Fixed

1. **DM admin group picker false-negative**
   - `my_chat_member` reconciliation previously passed a Telegram `Chat` object into `ChatMigrationService.reconcile_chat()`, which expects Ghostea `ChatContext`.
   - As a result, bot-added/permission lifecycle events could fail to register the group in `ghostea_chat_registry`.
   - Fixed by building a canonical `ChatContext` before reconciliation.
   - Group authorization now treats registry metadata as discovery-only and refreshes live chat type/forum state from Telegram.
   - Bot admin permissions are force-refreshed at upload workflow entry.

2. **Upload button did not actually publish**
   - Phase 7's `[Upload]` callback only moved the session to `READY` and never called the publisher.
   - Fixed: `[Upload]` now performs validation and invokes `ResourcePublishingService.publish()`.

3. **Publishing errors were not shown to the user**
   - `ResourcePublishError` was not caught by the upload callback.
   - Fixed with safe user-facing error handling.

4. **Closed topic publishing**
   - Closed topics remain allowed in the selector.
   - At publish time, Ghostea verifies the bot has `Manage Topics`, reopens the closed topic, then publishes.
   - Hidden General/deleted/inactive topics remain rejected.

5. **Workflow concurrency**
   - A `publishing` session is no longer treated as an interactive active session that can be cancelled by starting another workflow.
   - Expiry also never changes a `publishing` session to `expired`.

## Deployment

- No new SQL for these fixes.
- Render redeploy required.
- Vercel unchanged.
- UptimeRobot unchanged.
- If Phase 7 schema (`ghostea_upload_sessions` + `ghostea_resources`) has not yet been applied, apply the existing Phase 6/7 SQL sections once before deployment.
