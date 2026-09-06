-- Ghostea database schema
-- Run this once in Supabase SQL Editor.
-- The application uses the server-side SUPABASE_KEY only.
-- Never expose that key in the Vercel browser bundle.

-- Phase 1: canonical chat registry. One row per Telegram chat used by Ghostea.
-- This stores capabilities only; moderation settings remain group-scoped for now.
create table if not exists ghostea_chat_registry (
    chat_id bigint primary key,
    chat_type text not null check (chat_type in ('group', 'supergroup')),
    title text,
    username text,
    -- Telegram's public/private signal for group chats is the presence of a
    -- public username. Basic groups cannot be assigned a public username.
    visibility text not null default 'private'
        check (visibility in ('private', 'public')),
    is_forum boolean not null default false,
    first_seen_at timestamptz not null default now(),
    last_seen_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_ghostea_chat_registry_forum
    on ghostea_chat_registry (is_forum);

-- A basic Telegram group cannot be a Forum; forum is a supergroup
-- capability. Keep the invariant in the database as well as application code.
do $$
begin
    if not exists (
        select 1
        from pg_constraint
        where conname = 'ghostea_chat_registry_forum_supergroup_only'
          and conrelid = 'ghostea_chat_registry'::regclass
    ) then
        alter table ghostea_chat_registry
            add constraint ghostea_chat_registry_forum_supergroup_only
            check (is_forum = false or chat_type = 'supergroup');
    end if;
end $$;

-- Safe upgrade for databases created before Phase 11.
alter table ghostea_chat_registry
    add column if not exists visibility text not null default 'private';

do $$
begin
    if not exists (
        select 1
        from pg_constraint
        where conname = 'ghostea_chat_registry_visibility'
          and conrelid = 'ghostea_chat_registry'::regclass
    ) then
        alter table ghostea_chat_registry
            add constraint ghostea_chat_registry_visibility
            check (visibility in ('private', 'public'));
    end if;
end $$;

create index if not exists idx_ghostea_chat_registry_visibility
    on ghostea_chat_registry (visibility);

-- ============================================================
-- Ghostea Phase 3 — Forum topic persistence foundation
-- ============================================================
-- Topics are scoped by their parent chat. topic_id is NOT globally unique.
-- These tables are intentionally additive: existing warnings, settings,
-- reputation, verification and security state remain chat-scoped until the
-- later roadmap phases explicitly migrate them.
create table if not exists ghostea_topic_registry (
    chat_id bigint not null,
    topic_id bigint not null,
    name text,
    is_active boolean not null default true,
    is_closed boolean not null default false,
    is_hidden boolean not null default false,
    first_seen_at timestamptz not null default now(),
    last_seen_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    primary key (chat_id, topic_id)
);

alter table if exists ghostea_topic_registry
    add column if not exists is_hidden boolean not null default false;

create index if not exists idx_ghostea_topic_registry_chat_activity
    on ghostea_topic_registry(chat_id, is_active, updated_at desc);

create index if not exists idx_ghostea_topic_registry_chat_topic
    on ghostea_topic_registry(chat_id, topic_id);

create table if not exists ghostea_topic_settings (
    chat_id bigint not null,
    topic_id bigint not null,
    settings jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    primary key (chat_id, topic_id),
    constraint ghostea_topic_settings_object
        check (jsonb_typeof(settings) = 'object')
);

create index if not exists idx_ghostea_topic_settings_chat
    on ghostea_topic_settings(chat_id, updated_at desc);


create table if not exists ghostea_group_settings (
    chat_id bigint primary key,
    max_warnings integer not null default 3,
    mute1_minutes integer not null default 2,
    mute2_minutes integer not null default 5,
    flood_window_seconds integer not null default 8,
    flood_message_limit integer not null default 6,
    flood_mute_minutes integer not null default 10,
    blocked_link_action text not null default 'delete',
    abuse_filter_enabled boolean not null default true,
    spam_filter_enabled boolean not null default true,
    link_filter_enabled boolean not null default true,
    flood_protection_enabled boolean not null default true,
    welcome_enabled boolean not null default true,
    antiraid_enabled boolean not null default true,
    antiraid_join_limit integer not null default 8,
    antiraid_window_seconds integer not null default 20,
    antiraid_lock_minutes integer not null default 10,
    auto_cleanup_enabled boolean not null default false,
    verification_enabled boolean not null default true,
    verification_timeout_seconds integer not null default 120,
    min_account_age_days integer not null default 0,
    new_member_restriction_minutes integer not null default 0,
    repeated_message_window_seconds integer not null default 60,
    repeated_message_limit integer not null default 3,
    mention_spam_limit integer not null default 6,
    max_message_length integer not null default 4000,
    warning_decay_enabled boolean not null default true,
    warning_decay_days integer not null default 30,
    cleanup_max_age_days integer not null default 30,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists ghostea_warnings (
    chat_id bigint not null,
    user_id bigint not null,
    count integer not null default 0,
    updated_at timestamptz not null default now(),
    primary key (chat_id, user_id)
);

create table if not exists ghostea_warning_history (
    id bigint generated by default as identity primary key,
    chat_id bigint not null,
    user_id bigint not null,
    reason text not null,
    source text not null,
    active boolean not null default true,
    created_at timestamptz not null default now()
);

-- Safe upgrade for databases created by earlier Ghostea phases.
-- IMPORTANT: add the column before any index references it. Otherwise an
-- existing pre-warning-decay table causes the migration to stop early.
alter table ghostea_warning_history
  add column if not exists active boolean not null default true;

create index if not exists idx_ghostea_warning_history_chat_user
on ghostea_warning_history(chat_id, user_id, created_at desc);

create index if not exists idx_ghostea_warning_history_active
on ghostea_warning_history(chat_id, user_id, active, created_at desc);

create table if not exists ghostea_custom_filters (
    id bigint generated by default as identity primary key,
    chat_id bigint not null,
    filter_type text not null,
    value text not null,
    enabled boolean not null default true,
    created_at timestamptz not null default now(),
    unique(chat_id, filter_type, value)
);

-- Deployment repair note:
-- Existing installations may already have this table without topic_id.
-- The ALTER below is intentionally kept before every topic_id index.
create table if not exists ghostea_moderation_logs (
    id bigint generated by default as identity primary key,
    chat_id bigint not null,
    user_id bigint,
    topic_id bigint,
    action text not null,
    reason text,
    details text,
    created_at timestamptz not null default now()
);

-- Safe upgrade for databases created before Phase 6.
-- IMPORTANT: add topic_id before any index references it. Otherwise an
-- existing pre-topic table fails with "column topic_id does not exist".
alter table if exists ghostea_moderation_logs
  add column if not exists topic_id bigint;

create index if not exists idx_ghostea_moderation_logs_chat
on ghostea_moderation_logs(chat_id, created_at desc);
create index if not exists idx_ghostea_moderation_logs_chat_topic_time
on ghostea_moderation_logs(chat_id, topic_id, created_at desc);

create index if not exists idx_ghostea_moderation_logs_chat_topic_user_time
on ghostea_moderation_logs(chat_id, topic_id, user_id, created_at desc);

create table if not exists ghostea_join_events (
    id bigint generated by default as identity primary key,
    chat_id bigint not null,
    user_id bigint not null,
    joined_at timestamptz not null default now()
);
create index if not exists idx_ghostea_join_events_chat
on ghostea_join_events(chat_id, joined_at desc);

create table if not exists ghostea_raid_events (
    id bigint generated by default as identity primary key,
    chat_id bigint not null,
    action text not null,
    details text,
    created_at timestamptz not null default now()
);

create table if not exists ghostea_verifications (
    chat_id bigint not null,
    user_id bigint not null,
    token text not null,
    expires_at timestamptz not null,
    verified boolean not null default false,
    created_at timestamptz not null default now(),
    primary key(chat_id, user_id)
);

create table if not exists ghostea_reputation (
    chat_id bigint not null,
    user_id bigint not null,
    score integer not null default 0,
    positive_actions integer not null default 0,
    negative_actions integer not null default 0,
    updated_at timestamptz not null default now(),
    primary key(chat_id, user_id)
);

create table if not exists ghostea_cleanup_runs (
    id bigint generated by default as identity primary key,
    chat_id bigint not null,
    cutoff_at timestamptz not null,
    deleted_count integer not null default 0,
    created_at timestamptz not null default now()
);

create table if not exists ghostea_health_events (
    id bigint generated by default as identity primary key,
    chat_id bigint,
    status text not null,
    details text,
    created_at timestamptz not null default now()
);
create index if not exists idx_ghostea_health_events_time
on ghostea_health_events(created_at desc);

-- ============================================================
-- Ghostea Phase 18 — Migration & Lifecycle 2.0
-- The existing journal remains the durable recovery boundary for Group -> Supergroup
-- migrations. Phase 18 retries completed-table migrations safely and reconciles
-- authoritative post-migration Telegram metadata on the next update.

-- Ghostea Phase 10 — Telegram chat migration journal
-- ============================================================
-- Telegram may migrate a basic group into a supergroup. This journal makes
-- state migration resumable and prevents accidental target overwrites.
create table if not exists ghostea_chat_migrations (
    old_chat_id bigint not null,
    new_chat_id bigint not null,
    status text not null check (status in ('running','completed','blocked')),
    completed_tables jsonb not null default '[]'::jsonb,
    error text,
    updated_at timestamptz not null default now(),
    primary key (old_chat_id, new_chat_id)
);

create index if not exists idx_ghostea_chat_migrations_status
on ghostea_chat_migrations(status, updated_at desc);


-- ============================================================
-- Ghostea Phase 10 — User management audit trail
-- ============================================================
create table if not exists ghostea_user_admin_actions (
    id bigint generated by default as identity primary key,
    chat_id bigint not null,
    target_user_id bigint not null,
    admin_user_id bigint,
    action text not null,
    details text,
    created_at timestamptz not null default now()
);

create index if not exists idx_ghostea_user_admin_actions_chat
on ghostea_user_admin_actions(chat_id, created_at desc);

create index if not exists idx_ghostea_user_admin_actions_target
on ghostea_user_admin_actions(chat_id, target_user_id, created_at desc);


-- ============================================================
-- Ghostea Phase 11 — Persistent security/recovery state
-- ============================================================
create table if not exists ghostea_security_locks (
    chat_id bigint not null,
    lock_type text not null,
    expires_at timestamptz not null,
    original_permissions jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    primary key (chat_id, lock_type)
);

create index if not exists idx_ghostea_security_locks_expiry
on ghostea_security_locks(expires_at);


-- ============================================================
-- Ghostea Phase 14 — Scalable user directory + RBAC admins
-- ============================================================

create table if not exists ghostea_admins (
    id bigint generated by default as identity primary key,
    username text not null unique,
    display_name text not null default '',
    password_hash text not null,
    role text not null check (role in ('super_admin','admin','moderator','viewer')),
    enabled boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    last_login_at timestamptz
);

create index if not exists idx_ghostea_admins_role_enabled
on ghostea_admins(role, enabled);

create table if not exists ghostea_user_directory (
    chat_id bigint not null,
    user_id bigint not null,
    first_seen_at timestamptz not null default now(),
    last_activity timestamptz not null default now(),
    primary key(chat_id, user_id)
);

create index if not exists idx_ghostea_user_directory_chat_activity
on ghostea_user_directory(chat_id, last_activity desc);
create index if not exists idx_ghostea_warning_history_chat_user_time
on ghostea_warning_history(chat_id, user_id, created_at desc);

create index if not exists idx_ghostea_moderation_logs_chat_user_time
on ghostea_moderation_logs(chat_id, user_id, created_at desc);

create index if not exists idx_ghostea_join_events_chat_user_time
on ghostea_join_events(chat_id, user_id, joined_at desc);


-- Keep this table lightweight: it is an index of known users, not a copy of
-- Telegram's entire membership list.
create or replace view ghostea_user_directory_view as
with known as (
    select chat_id, user_id, min(first_seen_at) as first_seen_at,
           max(last_activity) as last_activity
    from ghostea_user_directory
    group by chat_id, user_id

    union

    select chat_id, user_id, min(joined_at), max(joined_at)
    from ghostea_join_events
    group by chat_id, user_id

    union

    select chat_id, user_id, min(created_at), max(created_at)
    from ghostea_moderation_logs
    where user_id is not null
    group by chat_id, user_id

    union

    select chat_id, user_id, min(created_at), max(created_at)
    from ghostea_warning_history
    group by chat_id, user_id

    union

    select chat_id, user_id, min(updated_at), max(updated_at)
    from ghostea_reputation
    group by chat_id, user_id
)
select
    k.chat_id,
    k.user_id,
    k.first_seen_at,
    k.last_activity,
    coalesce(w.count, 0) as warnings,
    coalesce(l.actions, 0) as actions,
    coalesce(r.score, 0) as reputation
from known k
left join ghostea_warnings w
  on w.chat_id = k.chat_id and w.user_id = k.user_id
left join (
    select chat_id, user_id, count(*)::integer as actions
    from ghostea_moderation_logs
    where user_id is not null
    group by chat_id, user_id
) l on l.chat_id = k.chat_id and l.user_id = k.user_id
left join ghostea_reputation r
  on r.chat_id = k.chat_id and r.user_id = k.user_id;

-- Phase 14 RBAC bootstrap:
-- Set GHOSTEA_SUPERADMIN_USERNAME (optional; defaults to "superadmin")
-- and keep GHOSTEA_ADMIN_PASSWORD in Render. The first successful login
-- creates that account as the initial Super Admin with a scrypt password hash.
