"""Phase 26 — portable backup/restore for Ghostea state.

Backups are provider-neutral JSONL data plus an integrity manifest. Secrets and
Telegram tokens are never read. Referenced resource objects are copied when a
storage provider is available.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping

GHOSTEA_TABLES = (
    "ghostea_chat_registry",
    "ghostea_topic_registry",
    "ghostea_topic_settings",
    "ghostea_group_settings",
    "ghostea_warnings",
    "ghostea_warning_history",
    "ghostea_custom_filters",
    "ghostea_moderation_logs",
    "ghostea_join_events",
    "ghostea_raid_events",
    "ghostea_verifications",
    "ghostea_reputation",
    "ghostea_cleanup_runs",
    "ghostea_health_events",
    "ghostea_chat_migrations",
    "ghostea_user_admin_actions",
    "ghostea_security_locks",
    "ghostea_admins",
    "ghostea_user_directory",
    "ghostea_upload_sessions",
    "ghostea_resources",
    "ghostea_schema_meta",
    "ghostea_schema_migrations",
)

FORMAT_VERSION = 1
CHUNK_SIZE = 1000


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _safe_name(value: str) -> str:
    value = str(value or "")
    if not value or "/" in value or "\\" in value or value in {".", ".."}:
        raise ValueError("Unsafe backup path")
    return value


def _rows(provider, table: str, chunk_size: int = CHUNK_SIZE):
    offset = 0
    while True:
        rows = provider.select(
            table,
            {"select": "*", "limit": str(chunk_size), "offset": str(offset)},
        )
        if not rows:
            return
        for row in rows:
            yield dict(row)
        if len(rows) < chunk_size:
            return
        offset += len(rows)


def _write_jsonl_gz(path: Path, provider) -> dict:
    counts = {}
    digest = hashlib.sha256()
    with gzip.open(path, "wb") as out:
        for table in GHOSTEA_TABLES:
            count = 0
            for row in _rows(provider, table):
                line = (_json({"table": table, "row": row}) + "\n").encode("utf-8")
                out.write(line)
                digest.update(line)
                count += 1
            counts[table] = count
    return {"counts": counts, "sha256": digest.hexdigest()}


def _copy_storage(path: Path, resources: Iterable[Mapping], storage) -> dict:
    objects = []
    if storage is None:
        return {"copied": 0, "objects": []}
    root = path / "objects"
    root.mkdir(parents=True, exist_ok=True)
    for row in resources:
        key = str(row.get("storage_key") or "").strip()
        if not key:
            continue
        # Use a deterministic local filename while preserving the key in metadata.
        object_id = hashlib.sha256(key.encode("utf-8")).hexdigest()
        target = root / object_id
        data = storage.get(key)
        target.write_bytes(bytes(data))
        objects.append({
            "key": key,
            "file": f"objects/{object_id}",
            "size": len(data),
            "sha256": hashlib.sha256(bytes(data)).hexdigest(),
        })
    return {"copied": len(objects), "objects": objects}


def create_backup(provider, output: str | os.PathLike, storage=None) -> Path:
    """Create an atomic backup directory.

    The destination becomes a directory containing manifest.json,
    database.jsonl.gz and (when possible) referenced resource objects.
    """
    destination = Path(output)
    parent = destination.parent
    parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(f"Backup destination already exists: {destination}")

    tmp = Path(tempfile.mkdtemp(prefix=f".{destination.name}.", dir=parent))
    try:
        db_meta = _write_jsonl_gz(tmp / "database.jsonl.gz", provider)
        # Resources are in the database stream; query them separately only to
        # discover referenced storage objects.
        resources = _rows(provider, "ghostea_resources")
        storage_meta = _copy_storage(tmp, resources, storage)
        manifest = {
            "format": "ghostea-backup",
            "format_version": FORMAT_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "database": db_meta,
            "storage": storage_meta,
        }
        (tmp / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        os.replace(tmp, destination)
        return destination
    except Exception:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
        raise


def verify_backup(path: str | os.PathLike) -> dict:
    root = Path(path)
    manifest_path = root / "manifest.json"
    data_path = root / "database.jsonl.gz"
    if not manifest_path.is_file() or not data_path.is_file():
        raise ValueError("Invalid Ghostea backup: manifest/database file missing.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("format") != "ghostea-backup" or manifest.get("format_version") != FORMAT_VERSION:
        raise ValueError("Unsupported Ghostea backup format.")
    digest = hashlib.sha256()
    with gzip.open(data_path, "rb") as stream:
        for line in stream:
            digest.update(line)
            json.loads(line)
    expected = manifest.get("database", {}).get("sha256")
    if digest.hexdigest() != expected:
        raise ValueError("Backup integrity check failed: database checksum mismatch.")
    for obj in manifest.get("storage", {}).get("objects", []):
        relative = str(obj.get("file") or "")
        if not relative.startswith("objects/"):
            raise ValueError(f"Backup storage object has an invalid path: {obj.get('key')}")
        file_path = root / "objects" / _safe_name(relative.split("/", 1)[1])
        if not file_path.is_file():
            raise ValueError(f"Backup storage object is missing: {obj.get('key')}")
        data = file_path.read_bytes()
        if len(data) != int(obj["size"]) or hashlib.sha256(data).hexdigest() != obj["sha256"]:
            raise ValueError(f"Backup storage integrity failed: {obj.get('key')}")
    return manifest


def restore_backup(provider, path: str | os.PathLike, storage=None, *, replace=False) -> dict:
    """Restore a verified backup.

    Restore is additive/upsert and safe to re-run. Full destructive replacement
    is intentionally not supported by the provider-neutral path because a
    generic DELETE-all operation is unsafe across PostgREST and PostgreSQL.
    """
    root = Path(path)
    manifest = verify_backup(root)
    if replace:
        raise ValueError("Destructive --replace restore is not supported; use a database-native snapshot restore.")
    restored = {table: 0 for table in GHOSTEA_TABLES}
    with gzip.open(root / "database.jsonl.gz", "rt", encoding="utf-8") as stream:
        for line in stream:
            item = json.loads(line)
            table = item.get("table")
            row = item.get("row")
            if table not in GHOSTEA_TABLES or not isinstance(row, dict):
                raise ValueError("Backup contains an invalid table or row.")
            provider.upsert(table, row)
            restored[table] += 1

    copied = 0
    if storage is not None:
        for obj in manifest.get("storage", {}).get("objects", []):
            file_path = root / "objects" / _safe_name(obj["file"].split("/", 1)[-1])
            storage.put(obj["key"], file_path.read_bytes())
            copied += 1
    return {"restored": restored, "storage_objects": copied}
