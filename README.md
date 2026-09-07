# Ghostea 👻

Production-ready Telegram moderation bot built with Python and `python-telegram-bot`.

## Architecture

```text
GitHub → Render (Ghostea bot + /health + admin API)
             ↓
          Supabase
             ↑
Vercel → Admin Dashboard
             ↑
        UptimeRobot
```

## Local Android/Termux test

```bash
pip install -r requirements.txt

export BOT_TOKEN="YOUR_BOT_TOKEN"
export SUPABASE_URL="https://YOUR_PROJECT.supabase.co"
export SUPABASE_KEY="YOUR_SERVER_SIDE_SUPABASE_KEY"
export DASHBOARD_API_KEY="YOUR_RANDOM_LONG_SECRET"
export DASHBOARD_ORIGIN="http://localhost:3000"

python main.py
```

Do not commit `.env`, bot tokens, Supabase server keys, or `data/warnings.json`.

## Telegram permissions

Add Ghostea as an administrator with:

- Delete Messages
- Restrict Members
- Ban Users

Disable Group Privacy in BotFather.

## Supabase

Run `database.sql` once in Supabase SQL Editor.

## Render

Use:

```text
Build: pip install -r requirements.txt
Start: python main.py
Health: /health
```

Render supplies `PORT` automatically.

Required environment variables:

```text
BOT_TOKEN
SUPABASE_URL
SUPABASE_KEY
DASHBOARD_API_KEY
DASHBOARD_ORIGIN
```

## UptimeRobot

Monitor:

```text
https://YOUR-RENDER-SERVICE.onrender.com/health
```

UptimeRobot monitors the service; it is not the process that hosts the bot.

## Main moderation flow

- abusive message → delete + warning
- warning 1 → configured mute (default 2 min)
- warning 2 → configured mute (default 5 min)
- warning 3 → real permanent Telegram ban
- admins/owners are excluded from automatic moderation

## Filter files

```text
ghostea/filters/abusive_words.txt
ghostea/filters/spam_patterns.txt
ghostea/filters/blocked_domains.txt
```

One entry per line. Use `/reloadfilters` after editing files on a running instance.

## Phase 2 — Topic Context Engine

Ghostea now resolves one canonical chat/message context for every supported
Telegram update.

Supported environments:

```text
Group                    → topic_id = null
Supergroup               → topic_id = null
Forum Supergroup/Topic   → topic_id = Telegram message_thread_id
```

Topic identifiers are scoped to their parent chat and are never treated as
globally unique. In-memory flood and repeated-message protection use the
`(chat_id, topic_id)` scope, so activity in one forum topic cannot trigger a
frequency/repetition action in another topic.

The persistence model remains group-scoped in Phase 2. Structured topic
columns/tables are intentionally deferred to the later storage phases.

## Phase 4–6

Includes welcome, anti-raid, group settings, verification gate, repeated-message/mention protection, reputation, analytics, CSV/JSON export, health API, and persistent moderation data.

## Important

The Vercel dashboard should never receive `SUPABASE_KEY`. It should call Ghostea's authenticated API using the dashboard API secret through a secure server-side/proxy setup.


## Phase 7 — Production hardening

- Secure Vercel server-side dashboard proxy
- HttpOnly/Secure/SameSite dashboard session
- Render API authentication + origin checks
- API rate limiting and payload limits
- Strict dashboard setting validation
- Generic API errors (no internal exception leakage)
- Warning increment serialization within the bot process
- Clean shutdown of the Render web server
- No browser exposure of `DASHBOARD_API_KEY`

## Phase 8 — Full Admin Control Center

The Vercel dashboard now provides a protected admin control center for configured groups.

Features:
- Group selection and live status
- Group moderation settings and protection switches
- Custom word/domain/pattern filters
- Analytics with warning/action breakdowns
- Recent moderation logs
- Mobile-responsive UI
- Secure Vercel server-side proxy; Render and Supabase secrets remain server-side

No new database migration is required for Phase 8; it uses the existing settings,
custom-filter, analytics and moderation-log tables.

## Phase 9 — Centralized Moderation Engine

Phase 9 routes message-content checks through one moderation decision layer.
It evaluates:

- abusive language
- spam patterns
- blocked links
- mention spam
- repeated messages
- excessive message length

Each detection receives a risk score and a deterministic priority. The score
is recorded in moderation logs/announcements; it does not bypass the normal
warning limit. Administrators remain exempt from automatic moderation.

Flood protection remains a separate action because it is based on message
frequency rather than message content.


## Phase 10 — User Management

The admin dashboard now includes a **Users** section.

Supported actions:

```text
Load User
Warn
Remove Warning
Reset Warnings
Mute
Unmute
Ban
Unban
```

A user profile includes:

- Telegram account/status when accessible
- Current warning count
- Reputation score
- Warning history
- Moderation history

Dashboard moderation actions are executed by the Telegram bot and audited in
`ghostea_user_admin_actions`.

Run the updated `database.sql` once in Supabase before using the new audit
table.

For safety, the bot refuses dashboard/automatic ban, mute, or warning actions
against Telegram administrators/owners.


## Phase 11 — Persistent Security & Recovery

Phase 11 hardens the two time-based security systems that previously depended
only on in-memory/runtime state.

### Anti-Raid recovery
- Anti-Raid now snapshots the group's original default permissions.
- The temporary lock is stored in `ghostea_security_locks`.
- The lock is automatically restored after its configured duration.
- Pending locks are recovered after a Render restart.
- The old `set_permissions(..., until_date=...)` approach was removed because
  `set_permissions` changes default chat permissions and does not support an
  `until_date`; timed member restrictions use `restrict_member` instead.

### Verification expiry enforcement
- Unverified members no longer simply become unrestricted when the verification
  timer expires.
- A background security worker checks expired verification records.
- Expired, still-present non-admin members are banned.
- Expired verification records are cleaned up.
- Verification records are removed immediately after successful verification.
- Pending verification expiry is recovered after a Render restart.

### Database
Run the updated `database.sql` once in Supabase. It adds:

```text
ghostea_security_locks
```

No new environment variables are required.


## Phase 12 — Moderation Risk Center

Phase 12 adds a read-only moderation intelligence layer to the dashboard.

- Risk Center shows the most active/high-risk users for a selected period.
- Risk is derived from existing moderation logs and warning history.
- Recent events receive more weight than older events using a seven-day half-life.
- Existing Phase 9 `risk_score` values are respected when present in log details.
- User profiles now include an advisory risk score and level.
- Risk intelligence never directly triggers a ban, mute, warning, or other moderation action.
- No new environment variables or database tables are required.

Risk levels:

```text
0–24   Low
25–49  Medium
50–74  High
75–100 Critical
```

These scores are advisory indicators for moderators, not proof of wrongdoing.


## Phase 13 — Dashboard Data Visibility Fix

Phase 13 fixes the Admin Dashboard Users and Risk Center data flow.

- Users now has a real directory backed by warning history, moderation logs and reputation.
- Users can be loaded directly from the table instead of manually knowing a Telegram ID.
- Risk Center is reachable through the Vercel proxy allowlist.
- Risk service is correctly attached to the dashboard web handler.
- User profiles continue to show advisory risk.
- Fixed an HTML section nesting issue between Moderation Logs and Risk Center.
- Existing moderation behavior is unchanged.


## Post-Phase 14 Reliability Fixes

The current build also includes a reliability/security pass: 
- dashboard async requests are executed on the Telegram application's event loop instead of creating a second event loop per HTTP request;
- warning decay is persistent and respects manual warning removal/reset;
- verification callbacks fail closed, are answered only once, and keep members restricted until the expiry worker makes the ban decision;
- verified/unmuted members inherit the group's default permissions instead of receiving an unnecessarily broad permission set;
- anti-raid recovery does not overwrite newer administrator permission changes;
- risk calculations include targeted user lookups and exact headline analytics counts;
- the known-user directory tracks normal message activity with throttled writes;
- dashboard filter regex values are validated before storage;
- dashboard moderation audit records retain the actual dashboard administrator ID;
- warning/history privacy is restricted so normal members can inspect only their own records.

If the database was created before warning-decay support, run the updated `database.sql` once. It adds the `active` flag/index to `ghostea_warning_history` safely.

## Phase 14 — Scale + RBAC Admin Dashboard

- Added database-backed dashboard admins with `super_admin`, `admin`, `moderator`, and `viewer` roles.
- Super Admin is the only role allowed to create, edit, disable, or delete dashboard admins.
- Passwords are stored as scrypt hashes, never plaintext.
- Server-side RBAC is enforced on Render; hiding dashboard buttons is not the security boundary.
- Added a lightweight known-user directory table/view so the Users tab does not scan three large tables for every refresh.
- Added short-lived settings/filter caches to reduce Supabase load.
- Increased proxy rate budget and changed group loading from six parallel requests to a sequential flow.
- Risk queries are bounded and request only required fields, with a visible sample cap for very busy groups.
- A 50,000-member Telegram group should not be treated as a list to load into the dashboard. Ghostea indexes users it actually observes; it does not attempt to enumerate all Telegram members.
- Run the Phase 14 SQL additions in Supabase once before using RBAC/optimized Users.


## Phase 1 — Group / Supergroup foundation

Ghostea now has a canonical chat context layer for supported Telegram chats:

- `group` → group-wide context, no topic
- `supergroup` → supergroup-wide context, no topic
- forum-enabled `supergroup` → forum capability is detected and a message's
  `message_thread_id` is exposed as `topic_id` for later topic-aware phases
- non-group chats are rejected by the same centralized context helper
- lightweight chat capability metadata is persisted in `ghostea_chat_registry`
  with a throttled update path, so this registry cannot become a per-message
  database write

**Deployment:** run the new Phase 1 `ghostea_chat_registry` section from
`database.sql` in the existing Supabase project before deploying this version.
Existing moderation settings remain group-scoped in Phase 1; topic-specific
settings and topic persistence are intentionally reserved for later roadmap
phases.


## Phase 3 — Topic persistence foundation

Phase 3 adds the persistent data model needed for forum-topic-aware phases
without changing existing group-wide moderation behavior.

### Topic registry

`ghostea_topic_registry` stores observed forum topics using the composite
identity `(chat_id, topic_id)`. It records the topic name when Telegram sends
topic creation/edit metadata, active/closed state, and lightweight activity
timestamps.

Ordinary topic messages update the registry on a throttled path; topic service
messages (created, edited, closed, reopened, deleted) are persisted
immediately.

### Topic settings

`ghostea_topic_settings` stores **only topic overrides** as JSONB. It does not
copy the group's default settings into every topic. The later settings
inheritance phase will resolve:

```text
Topic Override → Group Setting → Ghostea Default
```

Normal groups and non-forum supergroups do not create topic rows.

### Migration

Run the updated `database.sql` in the existing Supabase project. Phase 3 is
additive and does not alter or migrate existing warning, reputation,
verification, security, or moderation-log data. Those existing records remain
chat-scoped until their explicitly planned roadmap phases.

## Phase 5 — Moderation Engine Migration

Ghostea now passes a typed `ModerationContext` into the centralized moderation engine instead of embedding request identity (`_chat_id`, `_user_id`, `_scope_key`) inside the settings dictionary.

- Normal groups and non-forum supergroups use `(chat_id, None)` protection scope.
- Forum topic messages use `(chat_id, topic_id)`.
- Repeated-message detection uses the explicit moderation context.
- Flood protection uses the same explicit `(chat_id, topic_id)` scope.
- Effective topic settings from Phase 4 remain the engine configuration source.
- Warnings and punishments remain chat-wide by design; topic context is not used to create separate warning counters.
- No Phase 5 database migration is required.



## Phase 6 — Topic-aware persistence, logs, analytics and risk

Phase 6 persists forum-topic context in the moderation event stream without
changing the scope of member state.

### Moderation logs

`ghostea_moderation_logs.topic_id` is nullable:

```text
Normal Group / non-forum Supergroup → topic_id = NULL
Forum topic                        → topic_id = Telegram message_thread_id
```

The composite event context is `(chat_id, topic_id)`. Existing rows remain
valid with `NULL` topic IDs, so the migration is additive.

### Scope rules

The following remain **chat-wide by design**:

- warning count/history
- reputation
- verification
- anti-raid/security state
- joins
- dashboard admin actions

The moderation event stream is **topic-aware**. Automatic and manual
moderation actions performed from a forum topic record that topic ID.

### Analytics and Risk

Analytics and Risk APIs accept an optional `topic_id` query parameter. When
provided, moderation-log events are scoped to that topic. Warning history and
join/member-state data remain chat-wide because they represent the user's
state in the group rather than a single topic.

Existing callers can omit `topic_id` and continue to receive group-wide
results.

### Database migration

Run the updated `database.sql` once. Phase 6 safely adds:

```text
ghostea_moderation_logs.topic_id
idx_ghostea_moderation_logs_chat_topic_time
idx_ghostea_moderation_logs_chat_topic_user_time
```

No existing moderation data is deleted or rewritten.


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


## Phase 8 — Dashboard Architecture
The dashboard now exposes a unified scope selector. Normal groups and non-forum supergroups stay group-only; forum supergroups expose known topics and topic-aware Settings, Analytics, Moderation Logs, and Risk views. Topic settings use the Phase 4 inheritance model and only permit message-moderation overrides.

New dashboard API routes: `GET /api/groups/<chat_id>/topics`, `GET /api/groups/<chat_id>/topics/<topic_id>/settings`, and `PATCH /api/groups/<chat_id>/topics/<topic_id>/settings`.

## Phase 9 — Compatibility & scope hardening

Ghostea is now validated across the supported environment matrix:

```text
Group                    → chat-wide scope; no topic path
Supergroup               → chat-wide scope; no topic path
Forum Supergroup/Topic   → chat-wide member state + topic-aware event scope
```

Dashboard topic APIs reject non-forum chats and unknown topics. Topic lifecycle
updates preserve stored names and closed/open state, so edit/close/reopen events
cannot accidentally reopen or erase topic metadata. Phase 9 adds compatibility
regression tests for scope isolation and existing service boundaries.


## Phase 10 — Migration & Stress Hardening

Ghostea now includes production-oriented foundation hardening for long-running
Group/Supergroup deployments:

- Telegram basic Group → Supergroup chat-id migration support.
- Journaled, resumable state migration in `ghostea_chat_migrations`.
- Collision-safe migration: existing target chat state is never overwritten.
- Persistent state follows the new chat id, including forum topic registry/settings.
- Transient anti-spam and security recovery state for the old id is discarded.
- Supabase GET requests use bounded exponential retry for transient network/5xx/429 failures.
- Non-idempotent writes are intentionally not retried to avoid duplicate moderation logs.
- Phase 10 regression tests cover migration, collision safety and transient-state cleanup.

### Phase 10 deployment

Run the updated `database.sql` in Supabase before deploying this phase. The
migration journal is additive and does not delete existing application data.

The migration handler is automatic: Telegram service messages carrying
`migrate_to_chat_id` or `migrate_from_chat_id` are consumed before normal
message moderation.

For a production rollout, deploy the bot during a quiet period and monitor
Render logs for `Chat migration handled` / `Chat migration failed` messages.

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


## Phase 13 — Basic Group Compatibility

Ghostea now has an explicit compatibility boundary for Telegram **basic
groups** (`chat.type == "group"`).

Supported in basic groups:
- message deletion and content moderation
- warning state and warning history
- configured warning-limit escalation to a permanent ban
- default chat permission locks used by Anti-Raid
- chat-wide settings, filters, reputation, joins, analytics and dashboard data

Not supported per-member in basic groups:
- temporary mutes / unmute via `restrictChatMember`
- verification flows that require restricting an individual member

When a basic group receives a warning below its configured limit, Ghostea
records the warning and sends a warning-only response instead of attempting a
Telegram API call that the chat type cannot support. At the configured warning
limit, the existing ban escalation remains active.

Basic groups do not support forum topics. Their scope therefore remains
`(chat_id, None)` and no topic metadata is created.

Telegram can migrate a basic group to a supergroup. Ghostea's existing
migration journal continues to move persistent state to the new chat id; after
migration, the supergroup capability set automatically enables per-member
restriction and (if the supergroup is converted to a forum) topic support.

This phase does not add a database migration.


## Phase 14 — Supergroup Compatibility

Phase 14 hardens Ghostea's behavior for **normal (non-forum) supergroups**.

### Supported supergroup operations

```text
Message moderation      → delete + warning
Per-member mute/unmute  → supported through restrictChatMember
Permanent ban/unban      → supported
Default chat lock        → supported
Group-wide settings      → supported
Public username          → supported when Telegram exposes one
Topics/forum operations  → intentionally not enabled
```

The capability engine now exposes a dedicated `SupergroupCompatibility`
contract so normal supergroups do not accidentally inherit forum behavior.
Forum-specific topic management is reserved for Phase 15.

### Permission model

Chat-type capability and the bot's current administrator rights remain
separate. Telegram requires the bot to have the relevant administrator rights
for deletion, member restriction/ban, and default-permission changes. The
dashboard/API should therefore treat a supported operation as *available by
chat type*, not as proof that the bot currently has permission.

Unmute now prefers fresh group default permissions before restoring a member,
so later administrator changes are not overwritten by stale permission data.

No new database migration or environment variable is required for Phase 14.


## Phase 15 — Forum Supergroup Engine

Ghostea now has a dedicated `ForumTopicService` for Telegram **Forum
Supergroups**. Forum operations are gated by the centralized capability
engine and the bot's live `can_manage_topics` administrator permission.

### Topic lifecycle

```text
/topics                         → list Ghostea-known topics
/topiccreate <name>             → create a topic
/topicrename <name>             → rename the current topic
/topicclose [topic_id]          → close a topic
/topicreopen [topic_id]         → reopen a topic
/topicdelete [topic_id]         → delete a non-General topic
```

The current topic is resolved from Telegram's `message_thread_id`. Topic
metadata remains keyed by `(chat_id, topic_id)` and is persisted in the
existing `ghostea_topic_registry` table.

The General topic uses Telegram's dedicated General-topic methods for rename,
close and reopen. Ghostea refuses to delete topic id `1` because the General
topic is not a normal deletable forum topic.

Forum topic creation/edit/close/reopen/delete is never attempted in ordinary
groups or non-forum supergroups. A missing `can_manage_topics` permission
produces a clear user-facing error rather than a raw Telegram failure.

No new database migration or environment variable is required for Phase 15.


## Phase 16 — Topic-Aware Ghostea

Forum moderation now preserves the originating topic for automated bot notices.
Content detection, effective message-moderation settings, flood/repeat state,
and moderation telemetry use `(chat_id, topic_id)` where appropriate. Chat-wide
member state remains intentionally shared across topics: warnings, reputation,
verification, joins, anti-raid and bans/restrictions are membership-level Telegram
operations. Telegram member restrictions therefore mute a member for the whole
supergroup, not only the topic where the violation occurred.

The General topic (`topic_id=1`) uses Telegram's default message destination;
ordinary groups and non-forum supergroups never receive a thread id.


## Phase 17 — Public / Private Behaviour

Ghostea now treats chat visibility as a presentation/identity concern separate
from moderation capability.

- A supergroup/forum with a Telegram public username is exposed as `public`.
- A chat without a public username is exposed as `private`.
- Basic groups are normalized to `private`; stale/synthetic public metadata
  cannot make a basic group publicly addressable.
- Public groups expose a safe `https://t.me/<username>` identity link.
- Private groups never receive a fabricated public URL or username.
- Moderation features do not become weaker merely because a supergroup is
  private.
- Dashboard group data includes `visibility_info`, `access_label`, and
  `public_url` when applicable.
- `/chatinfo` shows the current chat type and public/private identity.
- Visibility is recomputed from canonical Telegram chat context and normalized
  again for dashboard registry data, reducing stale metadata leakage.

Private does not mean that no invite link can exist; it means Ghostea does not
have a public username-based address to display.


## Phase 18 — Migration & Lifecycle 2.0

Phase 18 hardens Telegram chat lifecycle transitions after the Group → Supergroup
migration boundary. The migration journal is resumable, completed tables are
not treated as collisions on retry, and the bot refreshes the authoritative
post-migration chat metadata from Telegram before reconciling its registry.

Lifecycle reconciliation keeps chat type, public/private visibility and forum
capability synchronized. If a persisted forum flag ever disappears, stored
topic rows are retained for history but marked inactive/closed rather than
being silently deleted.

Operationally:
- Group → Supergroup state follows the new Telegram chat ID.
- Interrupted migrations can resume from `ghostea_chat_migrations`.
- Target collisions remain fail-closed.
- Post-migration username/visibility/forum state is refreshed from Telegram.
- Stale topic state is retired if forum capability disappears.
- Existing chat-wide member/security state and topic-aware telemetry scopes are
  preserved.


## Phase 19 — Private Bot Topics (Optional)

Ghostea now supports Telegram's Bot API 9.3 private-chat forum topics as an
optional conversation-context feature.

### Requirements

Enable **forum topic mode for the bot in private chats** through BotFather.
Ghostea reads the bot account's `has_topics_enabled` capability at startup.

Supported private-chat topic operations:

```text
/topiccreate <name>
/topicrename <new name>
/topicdelete <topic_id>
```

When these commands are used inside a topic, the current `message_thread_id`
is resolved automatically.

Private-chat topic messages are persisted in the existing topic registry and
retain `(chat_id, topic_id)` isolation. Ghostea does **not** run group
moderation, warnings, flood mutes, verification, or member management against
private chats. This phase is a topic/context capability, not private-chat
moderation.

Telegram's Bot API currently supports creating, editing, deleting, and sending
messages to topics in private chats. The supergroup-only close/reopen
operations are intentionally not exposed for private chats, and there is no
Bot API `getForumTopics` listing method for private chats; `/topics` therefore
lists only topics Ghostea has observed/persisted.

No database migration or new environment variable is required. Existing
`ghostea_topic_registry` storage is reused.


## Phase H01 — Telegram API Contract Audit

Phase H01 is the first compatibility-hardening phase. It does not add user-facing
features. It creates one explicit, testable contract for the Telegram Bot API
surface Ghostea depends on.

Baseline:
- Telegram Bot API 10.3 (current project audit baseline)
- python-telegram-bot 22.x

The canonical contract is in `ghostea/services/telegram_contract.py` and covers:
- Telegram chat types and Ghostea-supported moderation chat types
- current `ChatPermissions` fields
- administrator rights used by Ghostea
- message/membership update families relevant to lifecycle handling
- forum/private-topic Bot API methods
- operation-specific chat-type and administrator-right requirements
- known permission-independent API constraints

Important audited semantics:
- `restrictChatMember` is supergroup-only.
- `banChatMember` works for groups and supergroups and uses `can_restrict_members`.
- `unbanChatMember` is a supergroup/channel operation; Ghostea intentionally scopes
  its moderation surface to supported groups/supergroups.
- `setChatPermissions` requires `can_restrict_members`.
- `deleteForumTopic` in a supergroup requires `can_delete_messages`, not
  `can_manage_topics`; private bot topics have no chat-admin permission requirement.
- `can_manage_direct_messages` is an administrator right, not a `ChatPermissions`
  member-permission field.
- private-chat topic mode is bot-account state exposed by `getMe()`.

The contract is intentionally descriptive and does not replace live permission
checks. H02 will harden authorization and permission-state recovery.

## Phase 20 — Final Compatibility + Production

Ghostea now has a final compatibility/readiness layer covering:

```text
Basic Group
    moderation + deletion + bans
    no per-member restriction
    no topics

Normal Supergroup
    full member moderation
    public/private identity
    no forum-topic operations

Forum Supergroup
    full member moderation
    topic-aware moderation/telemetry
    topic lifecycle management

Private Chat + Topics
    conversation/topic context only
    no group moderation
    create/edit/delete topic support when bot topic mode is enabled
```

Production diagnostics:
- `/compatibility` — live chat capabilities and bot permissions for the current chat
- `/readiness` — local production configuration/file checks
- `/health` — public liveness endpoint
- `/api/health` — authenticated database + production readiness status

The final readiness layer is intentionally fail-closed for unsupported chat
operations and does not claim that a capability is usable merely because the
chat type supports it; live bot admin permissions remain separate.


## Phase H02 — Permission & Authorization Hardening

H02 hardens live Telegram authorization without adding new user-facing
features. Stable chat capabilities remain separate from the bot's current
administrator permissions.

The live authorization layer is `ghostea/services/permission_service.py`:
- short-TTL bot permission cache
- short-TTL member/admin cache
- fail-closed lookup errors (`UNKNOWN` is never treated as non-admin)
- operation-specific checks for delete, restrict, ban, unban, default
  permissions, and forum topic management
- explicit cache invalidation on `my_chat_member` and `chat_member` updates

Telegram membership/permission changes are therefore reflected quickly while
avoiding a Telegram API lookup for every hot-path message.

Safety rules:
- a failed bot-permission lookup never authorizes a destructive operation
- a failed member lookup never grants an admin exemption
- unmute never falls back to a synthetic broad permission set
- default-permission anti-raid changes require `can_restrict_members`
- forum topic deletion requires `can_delete_messages`
- member restriction requires `can_restrict_members`
- ban/unban authorization is checked before the Telegram operation
- H02 does not change Ghostea's feature set; it only makes existing actions
  safer and more faithful to Telegram's live permission state.

Telegram lifecycle updates used for invalidation:
- `my_chat_member` invalidates the bot permission cache for that chat
- `chat_member` invalidates the affected member/admin cache entry

No database migration or new environment variable is required.
\n\n## Phase H03 — Moderation Action Reliability\n\nTelegram side effects now have explicit `ActionResult` outcomes. Detection and durable moderation state are kept distinct from whether a Telegram punishment actually succeeded. Failed delete/mute/ban/unban actions are never logged as successful actions, and rate-limit failures are classified as transient.\n

## Phase H04 — Message Update Coverage

H04 hardens the existing moderation pipeline against Telegram's distinct
message-update and content shapes without adding a new moderation feature.

Changes:
- `edited_message` updates are routed through the same moderation pipeline as
  new messages.
- Edited commands remain outside the moderation content pipeline.
- Text and media captions are the only content types passed to the existing
  text moderation engine.
- Non-text media and Telegram service payloads are explicitly classified and
  safely ignored by text moderation.
- Service/topic lifecycle updates can still update topic registry state even
  when Telegram provides no effective user.
- Migration service messages are processed before the user-identity guard.
- Moderation logs record whether the event was a new or edited message and
  whether the content came from text or a caption.

This phase intentionally does not change member identity semantics; ambiguous
`sender_chat`/anonymous-admin authorization remains part of H06.
\n\n## Phase H05 — Telegram Error & Rate-Limit Layer\n\nGhostea now centralizes Telegram failure classification and bounded retry policy.\nSafe/idempotent Telegram reads may retry transient network/server/timeout/rate-limit\nfailures using `retry_after` when supplied. Destructive or non-idempotent actions\nremain single-attempt and return explicit H03 action outcomes; they are never blindly\nreplayed after a 429. Rate-limit cooldown state is scoped to the affected chat.\nForbidden/permission failures, bad requests, transient failures, and unknown errors\nremain distinguishable for recovery and observability.\n

## Phase H06 — Member / Sender Identity Hardening

H06 keeps Telegram identity handling conservative. Ghostea distinguishes a
normal human sender, bot sender, chat-backed sender (`sender_chat`, including
anonymous administrators), and unknown/missing identity. A `sender_chat` is
never converted into a human member ID for moderation or member-management
actions. Replied-to chat-backed senders are not treated as moderation targets.

Authorization uncertainty remains fail-closed: inability to verify a target's
administrator status must not be interpreted as "not an admin" for destructive
commands. Bot senders and unknown identities are excluded from the member
moderation target path while service/topic bookkeeping can continue.


## Phase H07 — Forum & Topic Lifecycle Hardening

H07 hardens existing forum/topic lifecycle state. Topic service messages for create/edit/close/reopen and General hide/unhide are persisted without reopening or losing existing state. Telegram does not provide a dedicated Bot API topic-deleted update, so Ghostea does not fabricate one; definitive topic-id/not-found failures retire stale local records, while permission/transient failures do not. General topic ID 1 remains non-deletable. See `PHASE_H07_TOPIC_LIFECYCLE.md`.


## Phase H08 — Migration & Chat Lifecycle Hardening

H08 hardens Telegram Group → Supergroup migration and chat lifecycle reconciliation. After migration Ghostea fetches Telegram's current chat state, reconciles type/username/forum visibility, invalidates authorization caches, and keeps the durable migration journal resumable when reconciliation is temporarily unavailable. `my_chat_member` lifecycle updates also refresh persisted identity for supported group chats. No new user-facing feature is introduced.

## Phase H09 — State Recovery & Consistency

Phase H09 separates durable Ghostea state from disposable process-local state.
Supabase remains the durable store, while Telegram is authoritative for
Telegram-owned membership/permission state. Startup recovery clears transient
caches before recovering persisted anti-raid and verification state.

Transient Telegram failures no longer cause expired verification records or
anti-raid locks to be discarded. Recovery retries them safely. In-memory
flood/repeat/join windows are intentionally cleared after a process restart
rather than reconstructed from incomplete history.


## Phase H11 — Dashboard & API Reliability
Dashboard mutations are non-retried, reads have bounded timeout/retry behavior, current admin sessions are revalidated, Telegram permission service is shared with dashboard moderation, mutation caches are invalidated, and partial moderation outcomes are surfaced truthfully.


## Phase H12 — Production Observability & Diagnostics

Adds bounded structured operational events, correlation IDs, safe diagnostics, and lifecycle/action/error telemetry without changing moderation decisions. See `PHASE_H12_OBSERVABILITY.md`.

## Phase H13 — Telegram Compatibility Matrix

Ghostea now exposes a deterministic compatibility matrix covering Basic Groups, normal/public/private Supergroups, Forum Supergroups, Private Bot Topics, channel direct-message chats, and unsupported channels. Operation-level support is separated from live bot authorization, and Basic Group unban is explicitly unsupported because Telegram's `unbanChatMember` is a supergroup/channel operation.

## Phase H14 — Adversarial Regression Testing

Adds an offline failure-injection harness covering Telegram 403/400/429/timeout
behaviour, duplicate delivery, bot demotion, migration uncertainty, stale topic
boundaries, concurrent moderation, persistence failure, restart recovery, and
sender identity safety. H14 is stabilization-only and makes no new moderation
policy decisions. See `PHASE_H14_ADVERSARIAL_REGRESSION.md`.


## Phase H15 — Input Boundary & Schema Fuzz Hardening

H15 is another stabilization-only layer. It hardens untrusted scalar/container
boundaries used by Telegram payloads, persisted registry rows, and dashboard
data. Malformed chat IDs, topic IDs, update types, permission mappings,
visibility rows, and admin records now fail closed instead of escaping as
uncaught conversion/type errors. Unicode and extreme-length moderation inputs
are covered by a deterministic offline regression harness.

The H15 harness never calls Telegram, Supabase, or external services and is
included in local production-readiness checks. It does not introduce a new
moderation policy or capability.
