# Ghostea Deployment

## 1. GitHub
Push the complete repository. Never commit `.env`, BOT_TOKEN, SUPABASE_KEY or dashboard secrets.

## 2. Supabase
Create a project and run `database.sql` in SQL Editor.

The current `database.sql` is designed to be safe for existing Ghostea databases,
including pre-topic moderation logs and pre-warning-decay warning history.
It adds legacy columns before creating indexes that reference them; this order
is important for repeatable upgrades.

The bot uses Supabase REST from Render. Set:
- `SUPABASE_URL`
- `SUPABASE_KEY` (server-side secret; preferably the project's service-role/server key)

Do not put the database key in the Vercel frontend.

## 3. Render
Create a Web Service from this GitHub repo.

Build:
`pip install -r requirements.txt`

Start:
`python main.py`

Health:
`/health`

Environment:
`BOT_TOKEN`
`SUPABASE_URL`
`SUPABASE_KEY`
`DASHBOARD_API_KEY`
`DASHBOARD_ORIGIN`

Render supplies `PORT`.

## 4. Telegram
- Disable Group Privacy in BotFather.
- Add Ghostea as admin.
- Grant Delete Messages, Restrict Members and Ban Users.
- Use a group/supergroup for testing.

## 5. Vercel
Deploy the `dashboard/` directory as the Vercel project root.

Set these Vercel Environment Variables:
- `GHOSTEA_API_URL` = Render service URL
- `GHOSTEA_API_KEY` = same secret as Render `DASHBOARD_API_KEY`
- `GHOSTEA_SESSION_SECRET` = long random secret

The dashboard uses `/api/ghostea` as a server-side proxy, so the Render
API key is never placed in browser JavaScript.

Set Render `DASHBOARD_ORIGIN` to the exact Vercel dashboard origin, for example:
`https://ghostea.vercel.app`

## 6. UptimeRobot
Monitor:
`https://YOUR-RENDER-SERVICE.onrender.com/health`

UptimeRobot checks availability; Render remains the actual host/process.


## Phase 7 security model

The Vercel dashboard no longer sends the Render API key from browser JavaScript.

Vercel server-side environment variables:
- `GHOSTEA_API_URL`
- `GHOSTEA_API_KEY`
- `GHOSTEA_SESSION_SECRET`

The browser authenticates to the Vercel dashboard with the admin password.
Vercel creates an HttpOnly, Secure, SameSite session cookie and proxies only
the allowlisted Ghostea API endpoints. The Render API key remains server-side.

Render environment variables:
- `BOT_TOKEN`
- `SUPABASE_URL`
- `SUPABASE_KEY`
- `DASHBOARD_API_KEY`
- `DASHBOARD_ORIGIN`

Rotate any secret that has ever been committed to Git or shared publicly.


### Phase 10
Run the updated `database.sql` once in Supabase to create `ghostea_user_admin_actions`. No new environment variables are required.


## Phase 14 setup

1. Run the new Phase 14 section in `database.sql` in Supabase.
2. Render environment:
   - `GHOSTEA_SUPERADMIN_USERNAME` (optional; defaults to `superadmin`)
   - keep `GHOSTEA_ADMIN_PASSWORD` as the initial Super Admin password.
3. Vercel environment stays:
   - `GHOSTEA_API_URL`
   - `GHOSTEA_API_KEY`
   - `GHOSTEA_SESSION_SECRET`
4. Login with the Super Admin username/password once. Ghostea creates the
   database-backed Super Admin using a scrypt password hash.
5. Create other dashboard admins from **👑 Admins**. Only Super Admin can
   manage dashboard admins.
6. Roles: `super_admin`, `admin`, `moderator`, `viewer`.
7. Server-side RBAC is enforced on Render; dashboard UI hiding is only a
   convenience and is not the security boundary.


### Phase 1 database migration

Run the `ghostea_chat_registry` CREATE TABLE and index statements at the top of `database.sql` in the existing Supabase SQL editor. This is additive and does not alter existing moderation tables.


## Phase 2 — Group / Supergroup / Forum Topic context

No new Supabase migration is required for Phase 2. The bot resolves Telegram forum topic context at runtime. Existing database data remains chat-scoped; structured topic persistence is deferred to the storage phase.


## Phase 3 — Topic persistence migration

Run the updated `database.sql` once in the existing Supabase SQL editor. It
adds:

- `ghostea_topic_registry`
- `ghostea_topic_settings`
- indexes for chat/topic lookups

The migration is additive. Existing group-scoped moderation data is not
rewritten in Phase 3.

After deployment, forum topic messages will automatically populate the topic
registry. Normal groups and non-forum supergroups remain topic-free.


## Phase 4 — Settings Inheritance

Ghostea now resolves moderation settings using:

1. Topic override (forum topic only)
2. Group/Supergroup setting
3. Ghostea default

Only message-moderation settings are eligible for topic overrides. Chat-wide
controls such as warnings, verification, welcome, anti-raid, and warning decay
remain group-scoped so moving between topics cannot bypass moderation policy.

Normal groups and non-forum supergroups take a fast path with no topic settings
lookup. Forum messages use `(chat_id, topic_id)` as the scope.

Topic overrides are validated before persistence and are never allowed to inject
identity, timestamp, or unknown settings into the JSONB overlay.

### Phase 5 — Moderation Engine Migration

No new SQL migration is required for Phase 5. Deploy the Phase 5 source after Phase 4 and keep the Phase 3 topic tables/migrations already applied.

The moderation engine now receives an explicit request context. Forum flood/repeat protections are isolated by `(chat_id, topic_id)` while normal Groups/Supergroups remain `(chat_id, None)`.



## Phase 6 database migration

Before deploying the Phase 6 build, run the updated `database.sql` in the
existing Supabase project. The migration is safe for existing databases and
adds a nullable `topic_id` plus topic/time indexes to
`ghostea_moderation_logs`.

Existing group-wide records remain valid with `topic_id = NULL`.

After deployment, verify a forum-topic moderation event has a non-null
`topic_id`, while a normal Group/Supergroup moderation event stores `NULL`.


## Phase 7 — Existing Services Scope Audit

Ghostea now declares the scope of each existing service so forum-topic context
cannot accidentally split chat-wide member/security state.

**Chat-wide:** warnings, reputation, verification, anti-raid, welcome, joins,
RBAC, user management, security locks, settings, and custom filter definitions.

**Topic-aware:** message moderation context, flood/repeat state, moderation
logs, analytics event filtering, and risk event filtering.

**Forum-only:** topic registry metadata.

For topic-scoped analytics/risk, moderation events are filtered by topic while
warning state remains chat-wide. Normal groups and non-forum supergroups keep
`topic_id = NULL` and bypass topic-specific state.


### Phase 8 deployment note
No new database migration is required. Phase 8 uses the topic registry and topic settings tables created in Phase 3. Ensure the Phase 3 migration has already been applied.

## Phase 9 — Compatibility testing

No new Supabase migration is required for Phase 9. Deploy the Phase 9 source on
top of the Phase 8 database. Before production rollout, run:

```bash
PYTHONPATH=. pytest -q
```

The compatibility suite covers normal Groups, non-forum Supergroups and Forum
Supergroups, including topic isolation and topic lifecycle persistence.


## Phase 10 — Migration & resilience checklist

1. Run the Phase 10 section of `database.sql` in Supabase.
2. Deploy the bot and keep the previous release available for rollback.
3. Verify `/health` and `/api/health`.
4. For a Group → Supergroup migration, confirm the old chat's settings,
   warnings, moderation logs, reputation, verification/security state, user
   directory, and topic metadata now use the new chat id.
5. Confirm `ghostea_chat_migrations.status` is `completed`.
6. If a migration is `blocked`, do not manually delete target data just to
   force a merge. Inspect the target first; Ghostea refuses destructive
   implicit merges by design.
7. Watch Render logs during the first production migration and verify normal
   message moderation continues after the new supergroup id is observed.

## Phase 11 — Chat Identity & Visibility

Ghostea Phase 11 adds a canonical visibility field to the chat registry.

- Supported moderation chat types remain `group` and `supergroup`.
- `visibility` is derived from the Telegram chat username: `public` when a public username is exposed, otherwise `private`.
- Forum is a capability of a supergroup (`is_forum`); it is not a separate chat type.
- Basic Telegram groups cannot be assigned public usernames or native forum topics, so Ghostea does not invent a "group with topics" mode.
- The dashboard displays Private/Public alongside Group, Supergroup, and Forum Supergroup.
- Run the updated `database.sql` once to add the visibility column and forum invariant constraint.


## Phase 12 — Unified Capability Engine

Ghostea now resolves chat capabilities through `ghostea.services.chat_capabilities`.
Chat type, visibility, forum capability, and current topic-message context are
kept separate. `supports_*` flags describe what the Telegram chat type supports;
they do not grant the bot administrator permissions.

Supported community scopes:
- basic Group (private/public signal where exposed)
- Supergroup (private/public)
- Forum Supergroup (private/public)
- Forum topics only when the parent chat is a forum supergroup

Dynamic bot administrator permissions are represented separately by
`BotPermissions` and must be fetched/cached by callers when needed. The
message hot path does not perform a permission lookup per message.


## Phase 15 — Forum Supergroup Engine

No new Supabase migration or environment variable is required.

Before enabling topic-management commands in production, ensure Ghostea is an
administrator in the Forum Supergroup and has **Manage Topics**. The bot can
still moderate messages without this right, but topic create/rename/close/
reopen/delete commands are intentionally blocked until the right is present.

Recommended smoke test in a Forum Supergroup:

1. `/topiccreate Ghostea Test`
2. Open the new topic and run `/topicrename Renamed`
3. Run `/topicclose`
4. Run `/topicreopen`
5. Run `/topics`
6. Run `/topicdelete <topic_id>`
7. Confirm the topic registry reflects open/closed/deleted state.

The General topic (topic id `1`) may be renamed, closed and reopened, but is
never deleted by Ghostea.


## Phase 16
No new environment variables or database migration are required. Deploy the source normally; existing topic settings/logging tables are reused.


## Phase 18 — Migration & Lifecycle 2.0

No new environment variables are required. Existing deployments should keep the Phase 10 migration journal table; Phase 18 uses it for resumable migration recovery and post-migration metadata reconciliation.


## Phase 19 — Private Bot Topics

Phase 19 is optional. If private-chat topics are desired, enable the bot's
private forum-topic mode in BotFather. On startup Ghostea reads the Bot API
`User.has_topics_enabled` flag.

No new secrets or database tables are required.

Private topics are intentionally isolated from group moderation. Ghostea
persists their observed topic context but does not apply member moderation or
group lifecycle automation to direct chats.

Supported private topic management:
- create
- rename
- delete
- send/reply within the originating topic

Close/reopen and authoritative topic enumeration remain unavailable for private
chats through the Bot API and are therefore not presented as supported
operations.


## Phase H01 — Telegram API Contract Audit

No new environment variables or database migrations are required.

The source now contains `ghostea/services/telegram_contract.py`, a descriptive
Bot API 10.3 contract used by tests/readiness. It does not perform network
calls or grant permissions. Deploy H01 with the existing Phase 20 configuration.

H01 also corrects one Telegram contract mismatch in forum topic deletion:
supergroup `deleteForumTopic` requires the bot's `can_delete_messages`
administrator right. `can_manage_topics` alone is not sufficient.
\n\n## Phase H05 — Telegram Error & Rate-Limit Layer\n\nGhostea now centralizes Telegram failure classification and bounded retry policy.\nSafe/idempotent Telegram reads may retry transient network/server/timeout/rate-limit\nfailures using `retry_after` when supplied. Destructive or non-idempotent actions\nremain single-attempt and return explicit H03 action outcomes; they are never blindly\nreplayed after a 429. Rate-limit cooldown state is scoped to the affected chat.\nForbidden/permission failures, bad requests, transient failures, and unknown errors\nremain distinguishable for recovery and observability.\n