# Phase 26 — Backup, Restore & Disaster Recovery

Phase 26 adds a provider-neutral, integrity-checked Ghostea backup/restore path.

## Backup format

A backup directory contains:

```text
manifest.json
database.jsonl.gz
objects/
```

`database.jsonl.gz` stores every Ghostea application table as newline-delimited
JSON. `manifest.json` records row counts, creation time, format version and a
SHA-256 checksum. Referenced resource objects are copied into `objects/` with
individual SHA-256 checksums.

Secrets, bot tokens, dashboard passwords and provider credentials are never
read by the backup code.

## Commands

With the same environment variables used by Ghostea:

```bash
python scripts/ghostea_backup.py backup backups/ghostea-2026-09-13
python scripts/ghostea_backup.py verify backups/ghostea-2026-09-13
python scripts/ghostea_backup.py restore backups/ghostea-2026-09-13
```

Use `--no-storage` for a database-only backup.

Restore is deliberately **additive/upsert** and safe to repeat. A destructive
provider-neutral `--replace` operation is not supported because a generic
DELETE-all operation is unsafe across Supabase PostgREST and PostgreSQL.
For full database replacement, use a database-native snapshot/restore tool
such as PostgreSQL `pg_dump`/`pg_restore` with appropriate operational controls.

## Disaster-recovery procedure

1. Preserve the backup directory unchanged.
2. Run `verify` before any restore.
3. Provision the same Ghostea schema version on the destination database.
4. Configure the destination provider and storage credentials.
5. Run `restore`.
6. Verify dashboard health, group registry, resources and Telegram permissions.
7. For local storage, retain the backup `objects/` directory until all
   referenced resources are confirmed.

The provider-neutral backup is intended for Ghostea application state. Telegram
itself remains authoritative for current membership, permissions and chat
metadata, so restoring the database does not fabricate Telegram state.

## Operational recommendation

For production, keep multiple dated backups on storage independent from the
running Ghostea host, test restores periodically, and protect backup files
with filesystem/object-storage access controls and encryption at rest.

No database schema migration is introduced by Phase 26.
