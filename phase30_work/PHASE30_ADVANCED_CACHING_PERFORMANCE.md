# Phase 30 — Advanced Caching & Performance

Phase 30 adds bounded, process-local TTL/LRU caching for hot, read-mostly Ghostea state while keeping PostgreSQL/Supabase authoritative.

## Included

- bounded TTL/LRU cache primitive;
- cache hit/miss/eviction metrics;
- settings, custom-filter, and topic-settings caches use the bounded cache;
- existing write invalidation semantics are preserved;
- cache stampede protection remains for group settings;
- runtime cache clearing remains available for recovery/migration boundaries;
- malformed Supabase timeout/retry environment values no longer crash provider initialization;
- malformed PostgreSQL connection timeout values fall back safely;
- no new database migration.

## Environment

- `GHOSTEA_CACHE_TTL_SECONDS` — default `10`, bounded to 1–300 seconds;
- `GHOSTEA_CACHE_MAX_ENTRIES` — default `5000`, bounded to 100–100000.

Caches are per process and are never treated as durable state. Multi-instance deployments may have independent caches; successful writes invalidate the local cache and database remains the source of truth.
