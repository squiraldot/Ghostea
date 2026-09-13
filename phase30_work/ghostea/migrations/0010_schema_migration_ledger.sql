-- Ghostea Phase 27 migration 10: versioned migration ledger.
-- Safe, additive, transactional. No application rows are deleted or rewritten.
create table if not exists ghostea_schema_migrations (
    version integer primary key,
    name text not null,
    checksum text not null,
    applied_at timestamptz not null default now()
);

insert into ghostea_schema_migrations(version, name, checksum)
values (10, 'schema_migration_ledger', 'b75b790f4f9152c747b1d6427761acbb2732af0195c117a4ad39b4c8a6fbe1c1')
on conflict (version) do nothing;

insert into ghostea_schema_meta(schema_name, schema_version)
values ('ghostea', 10)
on conflict (schema_name) do update
set schema_version = greatest(ghostea_schema_meta.schema_version, excluded.schema_version);
