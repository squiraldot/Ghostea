-- Phase 29 — Durable background job queue.
create table if not exists ghostea_background_jobs (
    job_id text primary key,
    job_type text not null,
    payload jsonb not null default '{}'::jsonb,
    status text not null default 'pending'
        check (status in ('pending','running','succeeded','failed','dead')),
    attempts integer not null default 0 check (attempts >= 0),
    max_attempts integer not null default 5 check (max_attempts between 1 and 20),
    available_at timestamptz not null default now(),
    locked_by text,
    locked_at timestamptz,
    last_error text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    completed_at timestamptz
);

create index if not exists idx_ghostea_background_jobs_ready
    on ghostea_background_jobs(status, available_at);
create index if not exists idx_ghostea_background_jobs_locked
    on ghostea_background_jobs(status, locked_at);
create index if not exists idx_ghostea_background_jobs_type
    on ghostea_background_jobs(job_type, created_at desc);

-- Record the migration atomically so the schema version cannot drift from
-- the durable migration ledger. The checksum literal is normalized by the
-- migration catalog when calculating the expected checksum.
insert into ghostea_schema_migrations(version, name, checksum)
values (11, 'background_jobs', 'ee22b8a7923e7c811328fc86ae12450c733317bdc8e4b8d8517a62095aa89286')
on conflict (version) do nothing;

update ghostea_schema_meta
set schema_version = greatest(schema_version, 11)
where schema_name = 'ghostea';
