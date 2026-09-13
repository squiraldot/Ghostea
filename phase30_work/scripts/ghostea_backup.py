#!/usr/bin/env python3
"""Ghostea Phase 26 backup/restore CLI.

Uses the same configured provider as the application. It never prints secret
values and refuses unsafe backup paths.
"""
from __future__ import annotations
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ghostea.services.backup_restore import create_backup, restore_backup, verify_backup
from ghostea.services.deployment_profile import load_deployment_profile
from ghostea.storage.provider_factory import create_database_provider, create_storage_provider


def _parser():
    p = argparse.ArgumentParser(description="Ghostea backup/restore utility")
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("backup", "restore", "verify"):
        s = sub.add_parser(name)
        s.add_argument("path", help="Backup directory")
        if name == "backup":
            s.add_argument("--no-storage", action="store_true", help="Skip referenced resource objects")
    return p


def main(argv=None):
    args = _parser().parse_args(argv)
    db = storage = None
    try:
        profile = load_deployment_profile()
        db = create_database_provider(profile, url=os.getenv('SUPABASE_URL', ''), key=os.getenv('SUPABASE_KEY', ''))
        if args.command == "backup":
            if not args.no_storage:
                storage = create_storage_provider(profile)
            result = create_backup(db, args.path, storage=storage)
            print(f"Backup created: {result}")
        elif args.command == "verify":
            manifest = verify_backup(args.path)
            print(f"Backup verified: {manifest['created_at']}")
        else:
            storage = create_storage_provider(profile)
            result = restore_backup(db, args.path, storage=storage)
            print(f"Restore complete: {sum(result['restored'].values())} database rows, {result['storage_objects']} storage objects.")
        return 0
    except Exception as exc:
        print(f"Ghostea backup operation failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if db is not None:
            db.close()
        if storage is not None and hasattr(storage, "close"):
            storage.close()


if __name__ == "__main__":
    raise SystemExit(main())
