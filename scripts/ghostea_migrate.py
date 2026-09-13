#!/usr/bin/env python3
"""Ghostea schema migration helper.

  python scripts/ghostea_migrate.py --status
  python scripts/ghostea_migrate.py --plan
  python scripts/ghostea_migrate.py --sql > phase27_migrations.sql
  python scripts/ghostea_migrate.py --apply   # PostgreSQL only
"""
import argparse, json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ghostea.services.schema_migrations import migration_status, migration_plan, render_sql, apply_postgresql
from ghostea.services.deployment_profile import load_deployment_profile
from ghostea.storage.provider_factory import create_database_provider

def main():
    parser=argparse.ArgumentParser(description="Inspect/apply Ghostea versioned database migrations.")
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--status", action="store_true")
    group.add_argument("--plan", action="store_true")
    group.add_argument("--sql", action="store_true")
    group.add_argument("--apply", action="store_true")
    group.add_argument("--dry-run", action="store_true")
    args=parser.parse_args()

    profile=load_deployment_profile(os.environ)
    provider=create_database_provider(profile)
    try:
        if args.status:
            print(json.dumps(migration_status(provider), indent=2))
            return 0
        plan=migration_plan(provider)
        if args.plan:
            print(json.dumps([{"version":m.version,"name":m.name,"checksum":m.checksum} for m in plan], indent=2))
            return 0
        if args.sql:
            print(render_sql(plan), end="")
            return 0
        if args.dry_run:
            print(json.dumps(apply_postgresql(provider, dry_run=True), indent=2))
            return 0
        result=apply_postgresql(provider)
        print(json.dumps(result, indent=2))
        return 0
    finally:
        provider.close()

if __name__=="__main__":
    raise SystemExit(main())
