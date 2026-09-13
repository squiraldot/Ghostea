# Phase 19 — Storage Provider System

Ghostea now uses a real provider abstraction for binary storage.

## Providers
- `local`: VPS/self-hosted filesystem storage.
- `supabase`: Supabase Storage object API.
- `s3`: AWS S3 or S3-compatible object storage through boto3.

## Managed default
`GHOSTEA_STORAGE_PROVIDER=supabase` is the recommended managed configuration.
Set `GHOSTEA_SUPABASE_STORAGE_BUCKET` (default `ghostea`) and create that bucket
before publishing file resources.

## Custom S3
Set:
- `GHOSTEA_S3_BUCKET`
- `GHOSTEA_S3_ACCESS_KEY`
- `GHOSTEA_S3_SECRET_KEY`
- `GHOSTEA_S3_REGION`
- optional `GHOSTEA_S3_ENDPOINT_URL`

## Safety
All providers reject unsafe relative object keys and enforce a configurable
maximum object size. Explicit provider selection fails closed when credentials
are missing.

## Compatibility
Render + Supabase + Vercel remains supported. Self-hosted VPS uses PostgreSQL
plus local storage. Provider choice is independent for managed/custom profiles.
