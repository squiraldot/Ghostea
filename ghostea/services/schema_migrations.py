"""Phase 27 — ordered, checksummed database migrations.

The migration catalog is provider-neutral. PostgreSQL can apply migrations
transactionally; Supabase/PostgREST deployments receive the exact SQL plan for
manual execution in the provider's SQL editor.
"""
from __future__ import annotations
from dataclasses import dataclass
import hashlib, re
from pathlib import Path
from typing import Any

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"
_CHECKSUM_RE = re.compile(r"(values\s*\(\s*10\s*,\s*'schema_migration_ledger'\s*,\s*)'[^']*'", re.I)

@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str
    checksum: str

def _checksum(sql: str) -> str:
    normalized = _CHECKSUM_RE.sub(r"\1''", sql)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

def load_migrations() -> tuple[Migration, ...]:
    result=[]
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        prefix, _, name = path.stem.partition("_")
        if not prefix.isdigit():
            continue
        version=int(prefix)
        sql=path.read_text(encoding="utf-8")
        result.append(Migration(version, name or path.stem, sql, _checksum(sql)))
    result.sort(key=lambda x:x.version)
    versions=[m.version for m in result]
    if len(versions)!=len(set(versions)):
        raise ValueError("Duplicate Ghostea migration version")
    return tuple(result)

def migration_status(provider) -> dict[str, Any]:
    """Return current schema version and pending migrations.

    Providers without SQL execution still get a useful status through
    ghostea_schema_meta. Missing migration ledger is reported as bootstrap
    required rather than silently guessed.
    """
    migrations=load_migrations()
    rows=provider.select("ghostea_schema_meta", {
        "select":"schema_name,schema_version",
        "schema_name":"eq.ghostea","limit":"1",
    })
    current=int(rows[0]["schema_version"]) if rows else 0
    ledger_exists=provider.check_tables(["ghostea_schema_migrations"]).get("ghostea_schema_migrations", False)
    drift=[]
    if ledger_exists:
        rows=provider.select("ghostea_schema_migrations", {"select":"version,name,checksum", "limit":"1000"})
        known={m.version:m for m in migrations}
        for row in rows:
            version=int(row["version"])
            expected=known.get(version)
            if expected is None or row.get("checksum") != expected.checksum:
                drift.append(version)
    pending=[m.version for m in migrations if m.version>current]
    latest=max((m.version for m in migrations), default=current)
    if current > latest:
        drift.append(current)
    return {
        "current_version": current,
        "latest_version": latest,
        "pending": pending,
        "ledger_exists": ledger_exists,
        "checksum_drift": sorted(set(drift)),
        "ready_to_apply": not drift and (ledger_exists or current == 0),
    }

def migration_plan(provider) -> list[Migration]:
    status=migration_status(provider)
    if status["checksum_drift"]:
        raise ValueError(
            "Migration checksum drift detected; refusing to plan an upgrade: "
            + ", ".join(str(v) for v in status["checksum_drift"])
        )
    current=status["current_version"]
    return [m for m in load_migrations() if m.version>current]

def render_sql(migrations) -> str:
    migrations=tuple(migrations)
    if not migrations:
        return "-- Ghostea schema is already at the latest migration version.\n"
    chunks=["-- Ghostea Phase 27 migration plan. Review before execution."]
    for m in migrations:
        chunks += [f"\n-- Migration {m.version}: {m.name} (sha256:{m.checksum})", "begin;", m.sql.rstrip(), "commit;"]
    return "\n".join(chunks)+"\n"

def apply_postgresql(provider, *, dry_run=False) -> dict[str, Any]:
    """Apply pending migrations atomically, with an advisory lock.

    Only the PostgreSQL provider exposes execute_sql; this deliberately fails
    closed for REST-only providers.
    """
    migrations=migration_plan(provider)
    if dry_run:
        return {"applied": [], "pending": [m.version for m in migrations], "sql": render_sql(migrations)}
    if not hasattr(provider, "execute_sql"):
        raise TypeError("Provider does not support transactional SQL migrations")
    if not migrations:
        return {"applied": [], "pending": []}
    applied=[]
    for migration in migrations:
        provider.execute_sql("BEGIN;")
        try:
            provider.execute_sql("SELECT pg_advisory_xact_lock(hashtext('ghostea:schema:migrations'));")
            provider.execute_sql(migration.sql)
            provider.execute_sql("COMMIT;")
        except Exception:
            try: provider.execute_sql("ROLLBACK;")
            except Exception: pass
            raise
        applied.append(migration.version)
    return {"applied": applied, "pending": [m.version for m in load_migrations() if m.version>applied[-1]]}
