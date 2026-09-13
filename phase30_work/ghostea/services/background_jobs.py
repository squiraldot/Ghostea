"""Phase 29 — durable, bounded background jobs."""
import asyncio, json, logging, os, socket, time, uuid
from datetime import datetime, timedelta, timezone
from ghostea.config import (
    GHOSTEA_JOB_BATCH_SIZE, GHOSTEA_JOB_LEASE_SECONDS,
    GHOSTEA_JOB_MAX_ATTEMPTS, GHOSTEA_JOB_PAYLOAD_MAX_BYTES,
    GHOSTEA_JOB_WORKER_ENABLED, GHOSTEA_JOB_WORKER_POLL_SECONDS,
)
from ghostea.services.observability import OBSERVABILITY

logger = logging.getLogger("Ghostea")

def _now(): return datetime.now(timezone.utc)
def _iso(dt): return dt.astimezone(timezone.utc).isoformat()
def _error_text(error): return f"{error.__class__.__name__}: {error}".strip()[:2000]

class BackgroundJobQueue:
    """Persistent at-least-once queue with bounded retries and crash leases."""
    def __init__(self, store):
        self.store = store
        self.worker_id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:12]}"
        self._handlers = {}
        self._task = None
        self._stop = asyncio.Event()

    def register(self, job_type, handler):
        if not isinstance(job_type, str) or not job_type or len(job_type) > 100:
            raise ValueError("job_type must be a non-empty string <= 100 characters")
        self._handlers[job_type] = handler

    async def enqueue(self, job_type, payload=None, *, delay_seconds=0, max_attempts=None, job_id=None):
        if job_type not in self._handlers:
            raise ValueError(f"unregistered background job type: {job_type}")
        payload = dict(payload or {})
        encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        if len(encoded.encode("utf-8")) > GHOSTEA_JOB_PAYLOAD_MAX_BYTES:
            raise ValueError("job payload exceeds configured size limit")
        attempts = GHOSTEA_JOB_MAX_ATTEMPTS if max_attempts is None else max(1, min(int(max_attempts), 20))
        now = _now()
        row = {
            "job_id": str(job_id or uuid.uuid4()), "job_type": job_type, "payload": payload,
            "status": "pending", "attempts": 0, "max_attempts": attempts,
            "available_at": _iso(now + timedelta(seconds=max(0, float(delay_seconds)))),
            "updated_at": _iso(now),
        }
        if job_id is not None:
            existing = await self.store._call(
                self.store.db.select,
                "ghostea_background_jobs",
                {"job_id": f"eq.{row['job_id']}", "limit": "1"},
            )
            if existing:
                return existing[0]
        try:
            result = await self.store._call(self.store.db.insert, "ghostea_background_jobs", row, True)
        except Exception:
            # A deterministic job id may have been inserted by another worker
            # between the existence check and INSERT. Resolve that race without
            # hiding unrelated database failures.
            if job_id is None:
                raise
            existing = await self.store._call(
                self.store.db.select,
                "ghostea_background_jobs",
                {"job_id": f"eq.{row['job_id']}", "limit": "1"},
            )
            if not existing:
                raise
            return existing[0]
        OBSERVABILITY.emit("background_job_enqueued", job_type=job_type, job_id=row["job_id"])
        return result[0] if result else row

    async def _recover_expired_leases(self):
        cutoff = _iso(_now() - timedelta(seconds=GHOSTEA_JOB_LEASE_SECONDS))
        rows = await self.store._call(self.store.db.select, "ghostea_background_jobs", {
            "status": "eq.running", "locked_at": f"lt.{cutoff}", "select": "job_id", "limit": "50",
        })
        for row in rows:
            now = _now()
            await self.store._call(self.store.db.update, "ghostea_background_jobs", {
                "status": "pending", "locked_by": None, "locked_at": None,
                "available_at": _iso(now), "updated_at": _iso(now),
                "last_error": "worker lease expired; job returned to queue",
            }, {"job_id": f"eq.{row['job_id']}", "status": "eq.running"})

    async def _claim_one(self):
        now = _iso(_now())
        candidates = await self.store._call(self.store.db.select, "ghostea_background_jobs", {
            "status": "eq.pending", "available_at": f"lte.{now}",
            "order": "available_at.asc", "limit": "1",
        })
        if not candidates: return None
        candidate = candidates[0]; job_id = str(candidate["job_id"]); lock_time = _now()
        updated = await self.store._call(self.store.db.update, "ghostea_background_jobs", {
            "status": "running", "locked_by": self.worker_id, "locked_at": _iso(lock_time),
            "attempts": int(candidate.get("attempts", 0)) + 1, "updated_at": _iso(lock_time),
        }, {"job_id": f"eq.{job_id}", "status": "eq.pending"})
        return updated[0] if updated else None

    async def _finish(self, job, *, success=False, error=None):
        now = _now()
        if success:
            payload = {"status":"succeeded","locked_by":None,"locked_at":None,
                       "completed_at":_iso(now),"updated_at":_iso(now),"last_error":None}
        else:
            attempts = int(job.get("attempts", 1)); maximum = int(job.get("max_attempts", GHOSTEA_JOB_MAX_ATTEMPTS))
            if attempts >= maximum:
                payload = {"status":"dead","locked_by":None,"locked_at":None,
                           "completed_at":_iso(now),"updated_at":_iso(now),"last_error":_error_text(error)}
            else:
                delay = min(300, 2 ** max(0, attempts - 1))
                payload = {"status":"pending","locked_by":None,"locked_at":None,
                           "available_at":_iso(now + timedelta(seconds=delay)),
                           "updated_at":_iso(now),"last_error":_error_text(error)}
        await self.store._call(self.store.db.update, "ghostea_background_jobs", payload, {
            "job_id": f"eq.{job['job_id']}", "status": "eq.running", "locked_by": f"eq.{self.worker_id}"
        })

    async def run_once(self):
        await self._recover_expired_leases(); processed = 0
        for _ in range(GHOSTEA_JOB_BATCH_SIZE):
            job = await self._claim_one()
            if not job: break
            processed += 1; handler = self._handlers.get(job.get("job_type")); started = time.monotonic()
            try:
                if handler is None: raise RuntimeError(f"no handler registered for {job.get('job_type')}")
                result = handler(job.get("payload") or {})
                if asyncio.iscoroutine(result): await result
                await self._finish(job, success=True)
                OBSERVABILITY.emit("background_job_succeeded", job_type=job.get("job_type"),
                                   job_id=job.get("job_id"), duration_ms=round((time.monotonic()-started)*1000,2))
            except Exception as error:
                logger.exception("Background job failed: %s", job.get("job_id"))
                await self._finish(job, error=error)
                OBSERVABILITY.emit("background_job_failed", level="WARNING",
                                   job_type=job.get("job_type"), job_id=job.get("job_id"),
                                   error_type=error.__class__.__name__)
        return processed

    async def start(self):
        if not GHOSTEA_JOB_WORKER_ENABLED or self._task is not None: return
        self._stop.clear(); self._task = asyncio.create_task(self._run(), name="ghostea-background-worker")
        logger.info("Background job worker started: %s", self.worker_id)

    async def _run(self):
        while not self._stop.is_set():
            try:
                processed = await self.run_once()
                try: await asyncio.wait_for(self._stop.wait(), timeout=0.05 if processed else GHOSTEA_JOB_WORKER_POLL_SECONDS)
                except asyncio.TimeoutError: pass
            except asyncio.CancelledError: raise
            except Exception:
                logger.exception("Background worker loop failed")
                try: await asyncio.wait_for(self._stop.wait(), timeout=GHOSTEA_JOB_WORKER_POLL_SECONDS)
                except asyncio.TimeoutError: pass

    async def stop(self):
        self._stop.set(); task, self._task = self._task, None
        if task is not None:
            try: await asyncio.wait_for(task, timeout=10)
            except asyncio.TimeoutError:
                task.cancel()
                try: await task
                except asyncio.CancelledError: pass
        logger.info("Background job worker stopped: %s", self.worker_id)

    async def queue_depth(self):
        rows = await self.store._call(self.store.db.select, "ghostea_background_jobs", {
            "status":"in.(pending,running)", "select":"job_id", "limit":"1000"})
        return len(rows)
