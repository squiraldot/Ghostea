"""Phase 27 — ordered, checksummed database migrations.

The migration catalog is provider-neutral. PostgreSQL can apply migrations
transactionally; Supabase/PostgREST deployments receive the exact SQL plan for
manual execution in the provider's SQL editor.
"""
from __future__ import annotations
from dataclasses import dataclass
import hashlib, re, shutil, subprocess
from pathlib import Path
from typing import Any

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"
_CHECKSUM_RE = re.compile(
    r"(insert\s+into\s+ghostea_schema_migrations\s*\(\s*version\s*,\s*name\s*,\s*checksum\s*\)\s*"
    r"values\s*\(\s*\d+\s*,\s*'[^']*'\s*,\s*)'[^']*'",
    re.I,
)

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
        "ready_to_apply": not drift and (ledger_exists or current < 10),
        "bootstrap_required": not ledger_exists and current >= 10,
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
    chunks=["-- Ghostea migration plan. Review before execution."]
    for m in migrations:
        chunks += [
            f"\n-- Migration {m.version}: {m.name} (sha256:{m.checksum})",
            "begin;",
            "select pg_advisory_xact_lock(hashtext('ghostea:schema:migrations'));",
            m.sql.rstrip(),
            "commit;",
        ]
    return "\n".join(chunks)+"\n"



def _run_psql(database_url: str, *, sql: str) -> str:
    if not isinstance(database_url, str) or not database_url.strip():
        raise ValueError("DATABASE_URL is required for psql migration execution")
    psql = shutil.which("psql")
    if not psql:
        raise RuntimeError("psql command not found; install the PostgreSQL client first")
    completed = subprocess.run(
        [psql, "--no-psqlrc", database_url.strip(), "-v", "ON_ERROR_STOP=1", "-At", "-c", sql],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "psql query failed").strip()
        raise RuntimeError(f"psql query failed: {detail[-4000:]}")
    return (completed.stdout or "").strip()


def migration_status_psql(database_url: str) -> dict[str, Any]:
    """Read migration state through the local psql client without psycopg.

    This path is intended for Android/Termux and never requires the Python
    PostgreSQL driver. Missing legacy ledger/meta tables are handled safely.
    """
    migrations = load_migrations()
    meta_table = _run_psql(
        database_url,
        sql="select to_regclass('public.ghostea_schema_meta') is not null;",
    ).lower() == "t"
    if meta_table:
        raw = _run_psql(
            database_url,
            sql="select coalesce((select schema_version from ghostea_schema_meta where schema_name='ghostea' limit 1),0);",
        )
        current = int(raw or 0)
    else:
        current = 0

    ledger_exists = _run_psql(
        database_url,
        sql="select to_regclass('public.ghostea_schema_migrations') is not null;",
    ).lower() == "t"
    rows = []
    if ledger_exists:
        raw = _run_psql(
            database_url,
            sql="select version, name, checksum from ghostea_schema_migrations order by version;",
        )
        for line in raw.splitlines():
            parts = line.split("|", 2)
            if len(parts) == 3:
                rows.append({"version": int(parts[0]), "name": parts[1], "checksum": parts[2]})
    known = {m.version: m for m in migrations}
    drift = []
    for row in rows:
        expected = known.get(row["version"])
        if expected is None or row.get("checksum") != expected.checksum:
            drift.append(row["version"])
    if current > max((m.version for m in migrations), default=current):
        drift.append(current)
    pending = [m.version for m in migrations if m.version > current]
    return {
        "current_version": current,
        "latest_version": max((m.version for m in migrations), default=current),
        "pending": pending,
        "ledger_exists": ledger_exists,
        "checksum_drift": sorted(set(drift)),
        "ready_to_apply": not drift and (ledger_exists or current < 10),
        "bootstrap_required": not ledger_exists and current >= 10,
    }

def apply_with_psql(sql: str, database_url: str) -> dict[str, Any]:
    """Execute a rendered migration plan with the local `psql` CLI.

    This is useful on Android/Termux where a psycopg binary wheel may not be
    available. The URL is passed directly to psql without shell expansion.
    """
    if not isinstance(database_url, str) or not database_url.strip():
        raise ValueError("DATABASE_URL is required for psql migration execution")
    psql = shutil.which("psql")
    if not psql:
        raise RuntimeError("psql command not found; install the PostgreSQL client first")
    completed = subprocess.run(
        [psql, "--no-psqlrc", database_url.strip(), "-v", "ON_ERROR_STOP=1", "-f", "-"],
        input=sql,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "psql migration failed").strip()
        raise RuntimeError(f"psql migration failed: {detail[-4000:]}")
    return {"applied_via": "psql", "stdout": (completed.stdout or "").strip()[-4000:]}

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
