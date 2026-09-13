# Phase 23 — Deployment Profiles & Setup Wizard

Phase 23 makes the two first-class Ghostea deployment profiles easy to
select, validate, and bootstrap without exposing secrets.

## Profiles

- `managed`: Render + Supabase + Vercel
- `self_hosted`: VPS + PostgreSQL + local storage + VPS dashboard

## Setup helper

```bash
python scripts/ghostea_setup.py --profile managed --show-template
python scripts/ghostea_setup.py --profile managed --check
python scripts/ghostea_setup.py --profile self_hosted --show-template
python scripts/ghostea_setup.py --profile self_hosted --check
```

The helper only emits safe provider/profile metadata. It never prints secret
values. A failed check exits with status 1.

## Configuration behavior

Profile selection is deterministic. Selecting a profile sets its canonical
provider tuple before validation, preventing stale provider variables from
silently producing a mixed deployment.

Phase 23 introduces no database schema changes.

## Phase 24 — Custom Provider Support

Custom mode allows supported providers to be mixed independently. Examples:

- PostgreSQL + S3 + Vercel
- PostgreSQL + Supabase Storage + VPS dashboard
- Supabase REST + S3 + VPS dashboard

Use the setup helper with an explicit provider tuple:

```bash
python scripts/ghostea_setup.py --profile custom \
  --database postgresql --storage s3 --dashboard vercel --show-template
```

Supported values:

- database: `supabase_rest`, `postgresql`
- storage: `supabase`, `local`, `s3`
- dashboard: `vercel`, `vps`, `external`

Custom mode fails closed if the three provider choices are not explicitly
configured. Provider-specific environment variables are then checked by the
same setup/readiness layer used by the canonical profiles.

Phase 24 introduces no database schema changes.
