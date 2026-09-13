# Phase 18 — Self-Hosted Storage

## Goal

In `self_hosted` mode, uploaded Telegram resources are archived on the VPS
filesystem so the download callback does not depend on Telegram's stored file
reference as the primary storage layer.

Managed mode is unchanged: it continues to use the existing Telegram file ID
flow until the dedicated remote-storage provider work.

## Storage layout

Default Docker path:

```text
/app/data/storage/
└── resources/
    └── <resource-id>/
        └── <safe-original-filename>
```

The `/app/data` Docker volume is persistent, so container recreation does not
remove stored resources.

## Configuration

```env
GHOSTEA_STORAGE_PROVIDER=local
GHOSTEA_LOCAL_STORAGE_ROOT=/app/data/storage
GHOSTEA_LOCAL_STORAGE_MAX_BYTES=20971520
```

The default per-object limit is 20 MiB, matching the conservative Telegram bot
download boundary used by this implementation.

## Security

- storage keys are relative and traversal-safe
- absolute paths and `..` segments are rejected
- filenames are sanitized before use
- writes are atomic (`fsync` + `os.replace`)
- storage remains under the configured root
- Docker keeps the storage volume writable while the application filesystem
  remains read-only

## Publish/download behavior

For self-hosted file/photo resources:

1. Ghostea obtains the Telegram file.
2. It archives the bytes to local storage.
3. It publishes the resource message.
4. The resource record stores the local storage key/metadata.
5. Download callbacks read the VPS copy and send it to the requester.

If the local copy is missing, Ghostea reports a controlled error instead of
silently falling back to an external storage source.

URL resources do not create a local binary copy.

## Database change

Phase 18 adds four nullable columns to `ghostea_resources`:

- `storage_key`
- `storage_filename`
- `storage_size`
- `storage_content_type`

The migration is additive and idempotent. Existing managed resources remain
valid.

## Deployment

### Managed Render + Supabase + Vercel

No behavior change. Existing configuration remains valid.

### Self-hosted Docker

The existing `ghostea-data:/app/data` volume persists the local storage.

After updating the source:

```bash
docker compose -f docker-compose.selfhost.yml up -d --build
```

Run the canonical `database.sql` against the PostgreSQL database before using
new local-storage fields.

## Recovery

Include `/app/data/storage` in VPS backups. Database backups alone do not
contain the stored file bytes.
