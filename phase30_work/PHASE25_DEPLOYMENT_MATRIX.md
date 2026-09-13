# Phase 25 — Deployment Matrix & Compatibility Hardening

Ghostea now validates custom deployment topologies before startup/deployment without making network calls.

## Supported provider axes
- Database: `supabase_rest`, `postgresql`
- Storage: `supabase`, `local`, `s3`
- Dashboard: `vercel`, `vps`, `external`

All implemented adapters are orthogonal at the architecture layer. Provider-specific prerequisites are checked fail-closed by the setup helper.

## Validation added
- Supabase/PostgreSQL URL syntax
- S3 bucket naming and optional endpoint URL
- VPS dashboard origin syntax when configured
- Existing secret length checks remain enforced

This phase adds no database migration and no UptimeRobot changes. No network connection is performed by the compatibility checker.

Run:
```bash
python scripts/ghostea_setup.py --profile custom --database postgresql --storage s3 --dashboard vercel --check
```
