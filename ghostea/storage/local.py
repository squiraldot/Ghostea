"""Phase 18 — secure local filesystem storage for self-hosted deployments."""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9._-]+$")
DEFAULT_ROOT = Path(__file__).resolve().parents[2] / "data" / "storage"


class LocalStorage:
    """Durable local storage with traversal-safe keys and atomic writes."""

    def __init__(self, root: str | os.PathLike | None = None, max_bytes: int | None = None):
        configured = root or os.getenv("GHOSTEA_LOCAL_STORAGE_ROOT", "")
        self.root = Path(configured).expanduser() if configured else DEFAULT_ROOT
        raw_limit = max_bytes if max_bytes is not None else os.getenv(
            "GHOSTEA_LOCAL_STORAGE_MAX_BYTES", str(20 * 1024 * 1024)
        )
        self.max_bytes = max(1, int(raw_limit))
        self.root.mkdir(parents=True, exist_ok=True)
        self._root_resolved = self.root.resolve()

    @staticmethod
    def _normalize_key(key: str) -> str:
        key = str(key or "").strip().replace("\\", "/")
        if not key or key.startswith("/") or "\x00" in key:
            raise ValueError("Storage key must be a relative path.")
        parts = key.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            raise ValueError("Storage key contains an unsafe path segment.")
        if any(not _SAFE_SEGMENT.fullmatch(part) for part in parts):
            raise ValueError("Storage key contains an unsafe character.")
        return "/".join(parts)

    def _path(self, key: str) -> Path:
        normalized = self._normalize_key(key)
        candidate = (self.root / normalized).resolve()
        try:
            candidate.relative_to(self._root_resolved)
        except ValueError as exc:
            raise ValueError("Storage key escapes the configured storage root.") from exc
        return candidate

    def put(self, key: str, data: bytes, content_type: str | None = None):
        del content_type  # Reserved for future metadata backends.
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError("Storage data must be bytes-like.")
        payload = bytes(data)
        if len(payload) > self.max_bytes:
            raise ValueError(
                f"Stored object exceeds GHOSTEA_LOCAL_STORAGE_MAX_BYTES ({self.max_bytes})."
            )
        destination = self._path(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".ghostea-", dir=str(destination.parent))
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
        return str(destination.relative_to(self.root))

    def get(self, key: str) -> bytes:
        path = self._path(key)
        if not path.is_file():
            raise FileNotFoundError(key)
        return path.read_bytes()

    def delete(self, key: str):
        path = self._path(key)
        try:
            path.unlink()
        except FileNotFoundError:
            return False
        self._prune_empty_parents(path.parent)
        return True

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def size(self, key: str) -> int:
        return self._path(key).stat().st_size

    def _prune_empty_parents(self, directory: Path):
        while directory != self._root_resolved and self._root_resolved in directory.parents:
            try:
                directory.rmdir()
            except OSError:
                break
            directory = directory.parent
