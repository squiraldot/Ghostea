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

from ghostea.services.schema_migrations import migration_status, migration_plan, render_sql, apply_postgresql, apply_with_psql
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
    group.add_argument("--apply-psql", action="store_true", help="Apply the pending SQL with the local psql client (Termux-friendly)")
    args=parser.parse_args()

    profile=load_deployment_profile(os.environ)
    provider=create_database_provider(
        profile,
        url=os.getenv("SUPABASE_URL", ""),
        key=os.getenv("SUPABASE_KEY", ""),
    )
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
        if args.apply_psql:
            sql = render_sql(plan)
            if not plan:
                print(json.dumps({"applied_via": "psql", "applied": [], "pending": []}, indent=2))
                return 0
            result = apply_with_psql(sql, os.getenv("DATABASE_URL", ""))
            result["applied"] = [m.version for m in plan]
            result["pending"] = []
            print(json.dumps(result, indent=2))
            return 0
        result=apply_postgresql(provider)
        print(json.dumps(result, indent=2))
        return 0
    finally:
        provider.close()

if __name__=="__main__":
    raise SystemExit(main())
