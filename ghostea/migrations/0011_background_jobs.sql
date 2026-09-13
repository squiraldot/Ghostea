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
