"""Phase 32 — operational monitoring and alert evaluation.

The operational snapshot is intentionally provider-neutral and secret-free. It
combines liveness/readiness, durable queue health, process telemetry and cache
statistics into a bounded dashboard payload. Alerts are derived from current
state; no credentials or raw payloads are exposed.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
import time


from ghostea.config import (
    GHOSTEA_ALERT_PENDING_AGE_SECONDS, GHOSTEA_ALERT_DEAD_JOBS,
    GHOSTEA_ALERT_RECENT_ERRORS,
)

ALERT_PENDING_AGE_SECONDS = GHOSTEA_ALERT_PENDING_AGE_SECONDS
ALERT_DEAD_JOBS = GHOSTEA_ALERT_DEAD_JOBS
ALERT_RECENT_ERROR_EVENTS = GHOSTEA_ALERT_RECENT_ERRORS


def _utc_now():
    return datetime.now(timezone.utc)


def _parse_dt(value):
    if not value:
        return None
    try:
        raw = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(raw)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _count_recent_errors(events, window_seconds=300):
    cutoff = time.time() - max(60, int(window_seconds))
    return sum(1 for event in events if str(event.get("level", "")).upper() == "ERROR" and float(event.get("ts", 0) or 0) >= cutoff)


def _alert(code, severity, message, details=None):
    return {
        "code": str(code),
        "severity": str(severity),
        "message": str(message),
        "details": details or {},
    }


def build_operations_snapshot(db, *, observability, background_jobs=None, readiness=None):
    """Build a bounded, secret-free operational snapshot.

    Database errors are represented as degraded state instead of escaping from
    the diagnostics endpoint. The endpoint therefore remains useful during a
    partial outage.
    """
    snapshot = observability.snapshot(limit=200)
    db_ok = False
    schema_version = None
    schema_ledger = False
    db_error = None

    try:
        db_ok = bool(db.health_check())
    except Exception as exc:
        db_error = exc.__class__.__name__

    try:
        meta = db.select("ghostea_schema_meta", {"select": "schema_name,schema_version", "schema_name": "eq.ghostea", "limit": "1"})
        if meta:
            schema_version = meta[0].get("schema_version")
    except Exception:
        pass

    try:
        ledger = db.check_tables(["ghostea_schema_migrations"])
        schema_ledger = bool(ledger.get("ghostea_schema_migrations"))
    except Exception:
        schema_ledger = False

    queue = {"worker_running": False, "pending": 0, "running": 0, "dead": 0, "succeeded": 0}
    queue_error = None
    if background_jobs is not None:
        task = getattr(background_jobs, "_task", None)
        queue["worker_running"] = bool(task is not None and not task.done())
    try:
        for status in ("pending", "running", "dead", "succeeded"):
            queue[status] = int(db.count("ghostea_background_jobs", {"status": f"eq.{status}"}))
    except Exception as exc:
        queue_error = exc.__class__.__name__

    pending_old = 0
    try:
        cutoff = (_utc_now() - timedelta(seconds=ALERT_PENDING_AGE_SECONDS)).isoformat()
        pending_old = int(db.count("ghostea_background_jobs", {"status": "eq.pending", "updated_at": f"lt.{cutoff}"}))
    except Exception:
        pass

    cache = {}
    try:
        store = getattr(getattr(background_jobs, "store", None), "cache_stats", None)
        if store:
            cache = store()
    except Exception:
        cache = {}

    readiness = dict(readiness or {})
    recent_errors = _count_recent_errors(snapshot.get("events", []))
    alerts = []
    if not db_ok:
        alerts.append(_alert("database_unhealthy", "critical", "Database health check failed", {"error_type": db_error or "unknown"}))
    if readiness and not bool(readiness.get("ready", True)):
        failed = [c.get("name") for c in readiness.get("checks", []) if not c.get("ok")]
        alerts.append(_alert("readiness_failed", "critical", "Production readiness checks are failing", {"checks": failed[:20]}))
    if queue["dead"] >= ALERT_DEAD_JOBS:
        alerts.append(_alert("dead_jobs", "critical", "Background jobs are in the dead-letter state", {"count": queue["dead"]}))
    if pending_old:
        alerts.append(_alert("stale_jobs", "warning", "Background jobs have remained pending for too long", {"count": pending_old, "threshold_seconds": ALERT_PENDING_AGE_SECONDS}))
    if background_jobs is not None and not queue["worker_running"] and os.getenv("GHOSTEA_JOB_WORKER_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}:
        alerts.append(_alert("worker_stopped", "warning", "Background job worker is not running"))
    if recent_errors >= ALERT_RECENT_ERROR_EVENTS:
        alerts.append(_alert("recent_errors", "warning", "Multiple recent operational errors were recorded", {"count": recent_errors, "window_seconds": 300}))
    if queue_error:
        alerts.append(_alert("queue_metrics_unavailable", "warning", "Background queue metrics could not be read", {"error_type": queue_error}))

    return {
        "ok": db_ok and not any(a["severity"] == "critical" for a in alerts),
        "service": "ghostea",
        "generated_at": _utc_now().isoformat(),
        "process": {"pid": os.getpid(), "python": os.sys.version.split()[0]},
        "deployment": {
            "mode": os.getenv("GHOSTEA_DEPLOYMENT_MODE", "managed").strip().lower(),
            "database_provider": os.getenv("GHOSTEA_DATABASE_PROVIDER", "supabase_rest").strip().lower(),
            "storage_provider": os.getenv("GHOSTEA_STORAGE_PROVIDER", "supabase").strip().lower(),
            "dashboard_host": os.getenv("GHOSTEA_DASHBOARD_HOST", "vercel").strip().lower(),
            "update_mode": os.getenv("GHOSTEA_UPDATE_MODE", "polling").strip().lower(),
        },
        "database": {"healthy": db_ok, "schema_version": schema_version, "migration_ledger": schema_ledger},
        "queue": queue,
        "queue_health": {"stale_pending": pending_old, "stale_threshold_seconds": ALERT_PENDING_AGE_SECONDS},
        "cache": cache,
        "observability": {
            "recent_error_events_5m": recent_errors,
            "counts": snapshot.get("counts", {}),
            "durations": snapshot.get("durations", {}),
            "event_buffer_size": snapshot.get("buffer_size", 0),
            "recent_events": snapshot.get("events", [])[-50:],
        },
        "readiness": readiness,
        "alerts": alerts,
    }
