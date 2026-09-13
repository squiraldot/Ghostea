"""Phase 19 — remote storage providers.

The storage contract stays provider-neutral. These adapters intentionally use
small synchronous methods so the existing async services can run them via
asyncio.to_thread().
"""
from __future__ import annotations

import io
import os
import re
import urllib.error
import urllib.parse
import urllib.request

_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9._-]+$")


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


class SupabaseStorage:
    """Supabase Storage object API adapter.

    Uses the same server-side SUPABASE_KEY as the database REST adapter.
    The configured bucket must already exist and the server-side key must have
    permission to create/read/delete objects in it.
    """

    def __init__(self, url: str, key: str, bucket: str = "ghostea", max_bytes: int | None = None):
        self.base = str(url or "").rstrip("/")
        self.key = str(key or "").strip()
        self.bucket = str(bucket or "").strip()
        if not self.base or not self.key:
            raise RuntimeError("Supabase storage requires SUPABASE_URL and SUPABASE_KEY.")
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", self.bucket):
            raise RuntimeError("GHOSTEA_SUPABASE_STORAGE_BUCKET is invalid.")
        raw_limit = max_bytes if max_bytes is not None else os.getenv(
            "GHOSTEA_REMOTE_STORAGE_MAX_BYTES", str(20 * 1024 * 1024)
        )
        self.max_bytes = max(1, int(raw_limit))

    def _url(self, key: str) -> str:
        normalized = _normalize_key(key)
        encoded = "/".join(urllib.parse.quote(part, safe="") for part in normalized.split("/"))
        return f"{self.base}/storage/v1/object/{urllib.parse.quote(self.bucket, safe='')}/{encoded}"

    def _request(self, method: str, key: str, data: bytes | None = None, content_type: str | None = None):
        body = None if data is None else bytes(data)
        if body is not None and len(body) > self.max_bytes:
            raise ValueError(
                f"Stored object exceeds GHOSTEA_REMOTE_STORAGE_MAX_BYTES ({self.max_bytes})."
            )
        headers = {
            "Authorization": f"Bearer {self.key}",
            "apikey": self.key,
        }
        if body is not None:
            headers["Content-Type"] = content_type or "application/octet-stream"
            headers["x-upsert"] = "true"
        request = urllib.request.Request(
            self._url(key), data=body, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=max(3.0, float(os.getenv("SUPABASE_HTTP_TIMEOUT_SECONDS", "15")))) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            details = error.read().decode("utf-8", errors="replace")
            if error.code == 404:
                raise FileNotFoundError(key) from error
            raise RuntimeError(f"Supabase Storage HTTP {error.code}: {details}") from error
        except urllib.error.URLError as error:
            raise RuntimeError(f"Supabase Storage connection failed: {error}") from error

    def put(self, key: str, data: bytes, content_type: str | None = None):
        self._request("POST", key, data=data, content_type=content_type)
        return _normalize_key(key)

    def get(self, key: str) -> bytes:
        return self._request("GET", key)

    def delete(self, key: str):
        try:
            self._request("DELETE", key)
        except FileNotFoundError:
            return False
        return True

    def exists(self, key: str) -> bool:
        try:
            self._request("HEAD", key)
            return True
        except FileNotFoundError:
            return False


class S3CompatibleStorage:
    """S3-compatible object storage adapter using boto3.

    endpoint_url is optional, allowing AWS S3 or S3-compatible providers.
    boto3 is imported lazily so managed installations that do not select S3
    don't pay import cost at startup.
    """

    def __init__(
        self,
        bucket: str,
        access_key: str,
        secret_key: str,
        region: str = "us-east-1",
        endpoint_url: str = "",
        max_bytes: int | None = None,
        client=None,
    ):
        self.bucket = str(bucket or "").strip()
        self.max_bytes = max(1, int(max_bytes if max_bytes is not None else os.getenv(
            "GHOSTEA_REMOTE_STORAGE_MAX_BYTES", str(20 * 1024 * 1024)
        )))
        if not self.bucket or not access_key or not secret_key:
            raise RuntimeError(
                "S3 storage requires GHOSTEA_S3_BUCKET, GHOSTEA_S3_ACCESS_KEY, and GHOSTEA_S3_SECRET_KEY."
            )
        if client is None:
            try:
                import boto3
            except ImportError as exc:
                raise RuntimeError("S3 storage requires the boto3 package.") from exc
            client = boto3.client(
                "s3",
                region_name=region or "us-east-1",
                endpoint_url=endpoint_url or None,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
            )
        self.client = client

    @staticmethod
    def _key(key: str) -> str:
        return _normalize_key(key)

    def put(self, key: str, data: bytes, content_type: str | None = None):
        payload = bytes(data)
        if len(payload) > self.max_bytes:
            raise ValueError(
                f"Stored object exceeds GHOSTEA_REMOTE_STORAGE_MAX_BYTES ({self.max_bytes})."
            )
        kwargs = {"Bucket": self.bucket, "Key": self._key(key), "Body": io.BytesIO(payload)}
        if content_type:
            kwargs["ContentType"] = content_type
        self.client.put_object(**kwargs)
        return self._key(key)

    def get(self, key: str) -> bytes:
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=self._key(key))
            return response["Body"].read()
        except Exception as exc:
            response = getattr(exc, "response", None) or {}
            if isinstance(response, dict) and (response.get("ResponseMetadata", {}) or {}).get("HTTPStatusCode") == 404:
                raise FileNotFoundError(key) from exc
            raise

    def delete(self, key: str):
        self.client.delete_object(Bucket=self.bucket, Key=self._key(key))
        return True

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=self._key(key))
            return True
        except Exception as exc:
            response = getattr(exc, "response", None) or {}
            if isinstance(response, dict) and (response.get("ResponseMetadata", {}) or {}).get("HTTPStatusCode") == 404:
                return False
            raise
