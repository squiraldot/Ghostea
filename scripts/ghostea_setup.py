#!/usr/bin/env python3
"""Ghostea deployment setup/check helper.

Examples:
  python scripts/ghostea_setup.py --profile managed --show-template
  python scripts/ghostea_setup.py --profile self_hosted --check
  python scripts/ghostea_setup.py --profile custom --database postgresql --storage s3 --dashboard vercel --show-template
"""
import argparse
import json
import os
import sys
from pathlib import Path

# Allow direct execution from the repository root (the documented usage).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ghostea.services.deployment_setup import (
    build_setup_result, render_env_template,
)
from ghostea.services.deployment_profile import (
    SUPPORTED_DATABASE_PROVIDERS, SUPPORTED_STORAGE_PROVIDERS, SUPPORTED_DASHBOARD_HOSTS,
)


def main():
    parser = argparse.ArgumentParser(description="Configure/check a Ghostea deployment profile.")
    parser.add_argument("--profile", choices=("managed", "self_hosted", "custom"), required=True)
    parser.add_argument("--database", choices=SUPPORTED_DATABASE_PROVIDERS, help="Custom database provider")
    parser.add_argument("--storage", choices=SUPPORTED_STORAGE_PROVIDERS, help="Custom storage provider")
    parser.add_argument("--dashboard", choices=SUPPORTED_DASHBOARD_HOSTS, help="Custom dashboard host")
    parser.add_argument("--check", action="store_true", help="Check current environment.")
    parser.add_argument("--show-template", action="store_true", help="Print a non-secret env template.")
    args = parser.parse_args()
    if args.profile != "custom" and any((args.database, args.storage, args.dashboard)):
        parser.error("--database/--storage/--dashboard are only valid with --profile custom")
    result = build_setup_result(os.environ, args.profile, database=args.database, storage=args.storage, dashboard=args.dashboard)
    if args.show_template:
        print(render_env_template(args.profile, database=args.database, storage=args.storage, dashboard=args.dashboard))
    if args.check or not args.show_template:
        print(json.dumps({
            "ready": result.ready,
            "profile": result.profile.mode,
            "database_provider": result.profile.database_provider,
            "storage_provider": result.profile.storage_provider,
            "dashboard_host": result.profile.dashboard_host,
            "required_environment": list(result.required_env),
            "errors": list(result.errors),
        }, indent=2))
        return 0 if result.ready else 1
    # Template generation is a successful command even though the current
    # environment is intentionally incomplete.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
