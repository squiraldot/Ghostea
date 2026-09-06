# Phase H11 — Dashboard & API Reliability

Phase H11 hardens the existing dashboard without adding user-facing features.

- Dashboard mutations are never retried automatically.
- Read requests use bounded client/proxy timeouts and may be retried safely.
- Vercel-to-Render requests carry a request ID for correlation.
- Dashboard group GET caches are invalidated after mutations.
- `/api/auth/me` revalidates the signed session identity against current DB state.
- Dashboard user-management uses the same Telegram permission service as bot actions.
- Telegram action failures are mapped to truthful HTTP errors instead of `target_is_admin`.
- Warning responses explicitly report when the warning was recorded but its configured punishment failed.
- Browser-side user actions are serialized per `(chat_id,user_id)` to prevent duplicate concurrent mutations.
- State-changing requests are intentionally not retried to avoid duplicate moderation actions.
