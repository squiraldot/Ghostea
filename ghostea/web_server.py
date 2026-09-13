import asyncio
import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import threading
import time
from io import BytesIO
from pathlib import Path
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from ghostea.services.chat_capabilities import (
    capabilities_from_registry,
    resolve_forum_compatibility,
)
from ghostea.services.chat_visibility import visibility_from_registry
from ghostea.services.observability import OBSERVABILITY, new_request_id, set_request_id, reset_request_id


MAX_BODY_BYTES = 32 * 1024
RATE_WINDOW_SECONDS = 60
RATE_MAX_REQUESTS = 300
GET_CACHE_TTL = 5.0
DASHBOARD_SESSION_TTL_SECONDS = 8 * 60 * 60
DASHBOARD_STATIC_MAX_BYTES = 2 * 1024 * 1024
TELEGRAM_WEBHOOK_MAX_BYTES = 1024 * 1024
DASHBOARD_STATIC_CSP = (
    "default-src 'self'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src https://fonts.gstatic.com; "
    "script-src 'self' 'unsafe-inline'; "
    "connect-src 'self'; "
    "img-src 'self' data: blob:; "
    "frame-ancestors 'none'; base-uri 'self'"
)


def _b64encode(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value):
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _dashboard_session_secret():
    return os.getenv("GHOSTEA_SESSION_SECRET", "").strip().encode("utf-8")


def _dashboard_sign(payload):
    secret = _dashboard_session_secret()
    if not secret:
        return ""
    return _b64encode(hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).digest())


def _dashboard_make_session(admin):
    payload = ":".join((
        str(int(admin["id"])),
        str(admin["role"]),
        str(admin["username"]),
        str(int(time.time())),
        _b64encode(os.urandom(18)),
    ))
    return f"{_b64encode(payload.encode('utf-8'))}.{_dashboard_sign(payload)}"


def _dashboard_session_from_request(handler):
    secret = _dashboard_session_secret()
    if not secret:
        return None
    cookie = handler.headers.get("Cookie", "")
    match = re.search(r"(?:^|;\s*)ghostea_session=([^;]+)", cookie)
    if not match:
        return None
    parts = match.group(1).split(".")
    if len(parts) != 2:
        return None
    try:
        payload = _b64decode(parts[0]).decode("utf-8")
        fields = payload.split(":")
        if len(fields) != 5:
            return None
        admin_id, role, username, issued_at_raw, _nonce = fields
        issued_at = int(issued_at_raw)
        age = int(time.time()) - issued_at
        if age < 0 or age > DASHBOARD_SESSION_TTL_SECONDS:
            return None
        if not re.fullmatch(r"\d+", admin_id) or role not in ("super_admin", "admin", "moderator", "viewer"):
            return None
        if not username or len(username) > 128:
            return None
        expected = _dashboard_sign(payload)
        actual = parts[1]
        if not expected or len(expected) != len(actual):
            return None
        if not hmac.compare_digest(expected, actual):
            return None
        return {"admin_id": admin_id, "role": role, "username": username}
    except (ValueError, UnicodeError, binascii.Error):
        return None


def _is_vps_dashboard():
    return (
        os.getenv("GHOSTEA_DEPLOYMENT_MODE", "managed").strip().lower() == "self_hosted"
        and os.getenv("GHOSTEA_DASHBOARD_HOST", "vercel").strip().lower() == "vps"
    )


def _validate_filter_value(filter_type, value):
    value = str(value or "").strip()
    if not value or len(value) > 500:
        return False
    if filter_type == "pattern":
        try:
            re.compile(value)
        except re.error:
            return False
    return True


def _configured_origin():
    return os.getenv("DASHBOARD_ORIGIN", "").strip().rstrip("/")


def _json(handler, status, payload):
    started = getattr(handler, "_obs_started", None)
    if started is not None:
        OBSERVABILITY.observe_duration(
            "http_request",
            time.monotonic() - started,
        )
        OBSERVABILITY.emit(
            "http_response",
            status=int(status),
            path=urlparse(handler.path).path,
            method=getattr(handler, "command", ""),
        )
    body = json.dumps(payload, default=str).encode("utf-8")
    origin = _configured_origin()
    request_origin = handler.headers.get("Origin", "").strip().rstrip("/")

    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("Referrer-Policy", "no-referrer")
    handler.send_header("X-Frame-Options", "DENY")
    handler.send_header("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    handler.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")

    # /health is intentionally public. Protected API endpoints only grant
    # CORS to the configured dashboard origin.
    if origin and request_origin == origin:
        handler.send_header("Access-Control-Allow-Origin", origin)
        handler.send_header("Vary", "Origin")

    handler.send_header(
        "Access-Control-Allow-Headers",
        "Authorization, Content-Type",
    )
    handler.send_header(
        "Access-Control-Allow-Methods",
        "GET, PATCH, POST, DELETE, OPTIONS",
    )
    handler.end_headers()

    if status != 204:
        handler.wfile.write(body)


class DashboardHandler(BaseHTTPRequestHandler):
    store = None
    analytics = None
    admins = None
    user_management = None
    permission_service = None
    observability = OBSERVABILITY
    _async_loop = None
    _rate_lock = threading.Lock()
    _rate = defaultdict(deque)
    _cache_lock = threading.Lock()
    _cache = {}
    telegram_update_callback = None

    def log_message(self, fmt, *args):
        return

    def _run_async(self, coro):
        """Run a coroutine on the Telegram application's event loop.

        HTTP requests are handled by worker threads. Reusing the bot loop is
        important because Phase3Store contains asyncio synchronization
        primitives that must not be driven from a second event loop.
        """
        loop = type(self)._async_loop
        if loop is not None and loop.is_running():
            future = asyncio.run_coroutine_threadsafe(coro, loop)
            return future.result(timeout=45)
        return asyncio.run(coro)

    @staticmethod
    def _call_sync(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    @classmethod
    def _rate_limited(cls, handler):
        # Render sees the Vercel proxy as the caller. This is intentionally
        # conservative; the dashboard itself is authenticated separately.
        key = handler.client_address[0]
        now = time.monotonic()
        with cls._rate_lock:
            q = cls._rate[key]
            while q and q[0] <= now - RATE_WINDOW_SECONDS:
                q.popleft()
            if len(q) >= RATE_MAX_REQUESTS:
                return True
            q.append(now)
            # Render normally sees one proxy IP, so keep the limiter map from
            # growing forever when clients rotate addresses.
            if len(cls._rate) > 1024:
                stale = [key for key, values in cls._rate.items() if not values or values[-1] <= now - RATE_WINDOW_SECONDS]
                for stale_key in stale[:256]:
                    cls._rate.pop(stale_key, None)
            return False

    def _serve_dashboard(self):
        if not _is_vps_dashboard():
            return False
        parsed = urlparse(self.path)
        if parsed.path not in ("/", "/index.html"):
            return False
        root = Path(__file__).resolve().parent.parent / "dashboard"
        target = root / "index.html"
        try:
            body = target.read_bytes()
        except OSError:
            return _json(self, 503, {"error": "dashboard_unavailable"})
        if len(body) > DASHBOARD_STATIC_MAX_BYTES:
            return _json(self, 500, {"error": "dashboard_too_large"})
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        self.send_header("Content-Security-Policy", DASHBOARD_STATIC_CSP)
        self.end_headers()
        self.wfile.write(body)
        return True

    def _local_dashboard_proxy(self):
        """Authenticate same-origin VPS dashboard and inject the trusted API identity."""
        if getattr(self, "_local_dashboard_internal", False) or not _is_vps_dashboard():
            return False
        parsed = urlparse(self.path)
        if parsed.path != "/api/ghostea":
            return False
        query = parse_qs(parsed.query)
        action = query.get("action", [""])[0]
        if action == "logout" and self.command == "POST":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Set-Cookie", "ghostea_session=; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=0")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')
            return True
        if action == "login" and self.command == "POST":
            if self._rate_limited(self):
                return _json(self, 429, {"error": "rate_limited"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > MAX_BODY_BYTES:
                    return _json(self, 413, {"error": "payload_too_large"})
                payload = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(payload, dict) or not isinstance(payload.get("username"), str) or not isinstance(payload.get("password"), str):
                    return _json(self, 400, {"error": "credentials_required"})
                if not _dashboard_session_secret():
                    return _json(self, 500, {"error": "server_not_configured"})
                admin = self.admins and self._run_async(self.admins.authenticate(payload.get("username"), payload.get("password")))
                if not admin:
                    return _json(self, 401, {"error": "invalid_credentials"})
                session = _dashboard_make_session(admin)
                return self._set_dashboard_cookie_and_json(session, admin)
            except json.JSONDecodeError:
                return _json(self, 400, {"error": "invalid_json"})
            except Exception:
                return _json(self, 500, {"error": "internal_server_error"})
        session = _dashboard_session_from_request(self)
        if not session:
            return _json(self, 401, {"error": "login_required"})
        requested = query.get("path", [""])[0]
        if not requested.startswith("/api/") or requested.startswith("/api/ghostea"):
            return _json(self, 400, {"error": "invalid_path"})
        if self.command in ("POST", "PATCH"):
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_BODY_BYTES:
                return _json(self, 413, {"error": "payload_too_large"})
            raw = self.rfile.read(length)
            self.rfile = BytesIO(raw)
            self.headers["Content-Length"] = str(len(raw))
        else:
            self.rfile = BytesIO(b"")
        self.headers["Authorization"] = f"Bearer {os.getenv('DASHBOARD_API_KEY', '').strip()}"
        request_id = new_request_id("local")
        canonical = "\n".join((session["admin_id"], session["role"], session["username"], request_id))
        self.headers["X-Ghostea-Admin-Id"] = session["admin_id"]
        self.headers["X-Ghostea-Role"] = session["role"]
        self.headers["X-Ghostea-Username"] = session["username"]
        self.headers["X-Ghostea-Request-Id"] = request_id
        proxy_secret = os.getenv("GHOSTEA_PROXY_SIGNING_SECRET", "").strip().encode("utf-8")
        if len(proxy_secret) < 32:
            return _json(self, 500, {"error": "server_not_configured"})
        self.headers["X-Ghostea-Admin-Signature"] = _b64encode(hmac.new(proxy_secret, canonical.encode("utf-8"), hashlib.sha256).digest())
        self.path = requested
        self._local_dashboard_internal = True
        getattr(self, {"GET": "do_GET", "POST": "do_POST", "PATCH": "do_PATCH", "DELETE": "do_DELETE"}[self.command])()
        return True

    def _set_dashboard_cookie_and_json(self, session, admin):
        body = json.dumps({"ok": True, "admin": admin}, default=str).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Set-Cookie", f"ghostea_session={session}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age={DASHBOARD_SESSION_TTL_SECONDS}")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        self.end_headers()
        self.wfile.write(body)
        return True

    def _telegram_webhook(self):
        """Accept Telegram webhook updates on the existing Ghostea HTTP port."""
        update_mode = os.getenv("GHOSTEA_UPDATE_MODE", "polling").strip().lower()
        webhook_path = os.getenv("GHOSTEA_WEBHOOK_PATH", "/telegram/webhook").strip() or "/telegram/webhook"
        expected = os.getenv("GHOSTEA_WEBHOOK_SECRET_TOKEN", "").strip()
        if update_mode != "webhook":
            return False
        parsed = urlparse(self.path)
        if parsed.path != webhook_path or self.command != "POST":
            return False
        supplied = self.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not expected or not supplied or len(supplied) > 256 or not hmac.compare_digest(supplied, expected):
            return _json(self, 403, {"error": "forbidden"})
        content_type = self.headers.get("Content-Type", "")
        if not content_type.lower().startswith("application/json"):
            return _json(self, 415, {"error": "json_required"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except (TypeError, ValueError):
            return _json(self, 400, {"error": "invalid_content_length"})
        if length <= 0 or length > TELEGRAM_WEBHOOK_MAX_BYTES:
            return _json(self, 413, {"error": "payload_too_large"})
        try:
            raw = self.rfile.read(length)
            payload = json.loads(raw or b"{}")
            if not isinstance(payload, dict):
                return _json(self, 400, {"error": "object_required"})
            callback = type(self).telegram_update_callback
            if callback is None:
                return _json(self, 503, {"error": "webhook_not_ready"})
            accepted = bool(callback(payload))
            if not accepted:
                return _json(self, 503, {"error": "update_not_accepted"})
            return _json(self, 200, {"ok": True})
        except json.JSONDecodeError:
            return _json(self, 400, {"error": "invalid_json"})
        except Exception:
            OBSERVABILITY.emit("telegram_webhook_error", level="ERROR")
            return _json(self, 500, {"error": "internal_server_error"})

    def do_HEAD(self):
        """Handle HEAD health checks used by monitors such as UptimeRobot.

        HEAD must return the same status/headers as GET without a response
        body. /health is intentionally public, so monitoring does not require
        dashboard authentication or the protected API key.
        """
        parsed = urlparse(self.path)
        path = parsed.path

        if self._serve_dashboard():
            return
        if self._local_dashboard_proxy():
            return

        if path == "/health":
            # Build the same health response headers as GET, but do not write
            # the JSON body. This makes UptimeRobot's default HEAD monitor
            # receive a clean 200 instead of BaseHTTPRequestHandler's 501.
            body = json.dumps({
                "ok": True,
                "service": "ghostea",
                "status": "running",
            }).encode("utf-8")
            origin = _configured_origin()
            request_origin = self.headers.get("Origin", "").strip().rstrip("/")

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            if origin and request_origin == origin:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
            self.send_header(
                "Access-Control-Allow-Headers",
                "Authorization, Content-Type",
            )
            self.send_header(
                "Access-Control-Allow-Methods",
                "GET, HEAD, PATCH, POST, DELETE, OPTIONS",
            )
            self.end_headers()
            return

        # Keep unsupported HEAD endpoints consistent with the existing server
        # behavior rather than accidentally exposing protected API routes.
        self.send_error(501, "Unsupported HEAD endpoint")

    def do_OPTIONS(self):
        _json(self, 204, {})

    @classmethod
    def _cached_json(cls, key):
        now = time.monotonic()
        with cls._cache_lock:
            item = cls._cache.get(key)
            if item and item[0] > now:
                return item[1]
            if item:
                cls._cache.pop(key, None)
        return None

    @classmethod
    def _put_cache(cls, key, payload):
        with cls._cache_lock:
            cls._cache[key] = (time.monotonic() + GET_CACHE_TTL, payload)
        return payload

    @classmethod
    def _invalidate_cache(cls, prefix=None):
        with cls._cache_lock:
            if prefix is None:
                cls._cache.clear()
            else:
                for key in [k for k in cls._cache if k.startswith(prefix)]:
                    cls._cache.pop(key, None)

    def _authorized(self):
        expected = os.getenv("DASHBOARD_API_KEY", "").strip()
        supplied = self.headers.get("Authorization", "")
        return bool(expected) and bool(supplied) and hmac.compare_digest(supplied, f"Bearer {expected}")

    def _proxy_identity_valid(self):
        """Verify the Vercel proxy authenticated the dashboard identity.

        The API key authenticates the proxy itself; this separate signature
        prevents anyone who can replay that key from forging a super-admin
        identity through X-Ghostea-* headers.
        """
        import base64

        secret = os.getenv("GHOSTEA_PROXY_SIGNING_SECRET", "").strip().encode("utf-8")
        admin_id = self.headers.get("X-Ghostea-Admin-Id", "")
        role = self.headers.get("X-Ghostea-Role", "")
        username = self.headers.get("X-Ghostea-Username", "")
        request_id = self.headers.get("X-Ghostea-Request-Id", "")
        supplied = self.headers.get("X-Ghostea-Admin-Signature", "")
        if not secret or not admin_id or not role or not username or not request_id or not supplied:
            return False
        if len(admin_id) > 32 or len(role) > 32 or len(username) > 128 or len(request_id) > 128 or len(supplied) > 128:
            return False
        canonical = "\n".join((admin_id, role, username, request_id)).encode("utf-8")
        expected = hmac.new(secret, canonical, hashlib.sha256).digest()
        try:
            supplied_bytes = base64.urlsafe_b64decode(supplied + "=" * (-len(supplied) % 4))
        except Exception:
            return False
        return hmac.compare_digest(expected, supplied_bytes)

    def _origin_allowed(self):
        origin = _configured_origin()
        request_origin = self.headers.get("Origin", "").strip().rstrip("/")
        # Vercel's server-side proxy intentionally does not send a browser
        # Origin header. Direct browser calls must match the configured origin.
        return not origin or not request_origin or request_origin == origin

    def _verify_and_link_group(self, chat_id, linked_by):
        """Verify a Telegram chat and explicitly link it for this deployment.

        Linking is intentionally verified with Telegram's own chat/member
        methods instead of the general permission cache.  This endpoint is a
        control-plane operation: it must work even when the chat is already in
        the registry but has not yet been explicitly linked, and it must return
        a useful distinction between "bot is not an admin" and an API lookup
        failure.
        """
        chat_id = int(chat_id)
        policy = self.permission_service.error_policy

        try:
            chat = self._run_async(
                policy.call_read(
                    lambda: self.server.bot.get_chat(chat_id),
                    scope_id=chat_id,
                )
            )
        except Exception as exc:
            # Telegram's getChat accepts integer chat IDs, including negative
            # supergroup IDs.  Preserve the actual failure category so the
            # dashboard does not turn a normal Telegram rejection into the
            # misleading generic telegram_link_verification_failed message.
            name = exc.__class__.__name__
            code = getattr(exc, "code", None)
            if name == "BadRequest" or code == 400:
                raise ValueError("telegram_chat_not_found") from exc
            raise

        if getattr(chat, "type", None) not in ("group", "supergroup"):
            raise ValueError("unsupported_chat_type")

        try:
            me = self._run_async(
                policy.call_read(
                    self.server.bot.get_me,
                    scope_id=chat_id,
                )
            )
        except Exception as exc:
            raise PermissionError("telegram_bot_identity_unverifiable") from exc

        try:
            bot_member = self._run_async(
                policy.call_read(
                    lambda: self.server.bot.get_chat_member(chat_id, me.id),
                    scope_id=chat_id,
                )
            )
        except Exception as exc:
            # getChatMember is the canonical Bot API check.  If Telegram
            # rejects that lookup, try the administrator list once.  This
            # makes linking resilient to edge permission behavior while
            # remaining fail-closed.
            try:
                admins = self._run_async(
                    policy.call_read(
                        lambda: self.server.bot.get_chat_administrators(chat_id),
                        scope_id=chat_id,
                    )
                )
            except Exception as admin_exc:
                raise PermissionError("telegram_bot_membership_unverifiable") from admin_exc
            bot_member = next(
                (member for member in admins
                 if getattr(getattr(member, "user", None), "id", None) == me.id),
                None,
            )
            if bot_member is None:
                raise PermissionError("bot_not_in_group") from exc

        status = str(getattr(bot_member, "status", ""))
        if status in ("left", "kicked"):
            raise PermissionError("bot_not_in_group")
        if status not in ("administrator", "creator"):
            raise PermissionError("bot_not_admin")

        self._run_async(self.store.link_chat(chat, linked_by=linked_by))
        # Materialize default settings so a newly dashboard-linked group is
        # immediately visible to /api/groups and existing dashboard features.
        self._run_async(self.store.get_settings(chat_id))
        self._invalidate_cache("groups:")
        return {
            "ok": True,
            "chat_id": chat_id,
            "title": getattr(chat, "title", None),
            "chat_type": getattr(chat, "type", None),
            "username": getattr(chat, "username", None),
            "is_forum": bool(getattr(chat, "is_forum", False)),
            "message": "Group verified and linked successfully.",
        }

    def _require_permission(self, permission):
        role = self.headers.get("X-Ghostea-Role", "")
        admin_id = self.headers.get("X-Ghostea-Admin-Id", "")
        if self.admins and self.admins.allowed(role, permission):
            try:
                current = self._run_async(
                    self.admins.authorize(admin_id, role)
                )
            except Exception:
                current = None
            if current:
                return True
        _json(self, 403, {"error": "permission_denied"})
        return False

    def _forum_chat_exists(self, chat_id):
        """Return True only when the registered chat is a forum supergroup."""
        rows = self._call_sync(
            self.store.db.select,
            "ghostea_chat_registry",
            {"chat_id": f"eq.{int(chat_id)}", "limit": "1"},
        )
        return bool(
            rows and capabilities_from_registry(rows[0]).supports_topics
        )

    def _require_forum_topic(self, chat_id, topic_id=None, require_active=False):
        if not self._forum_chat_exists(chat_id):
            _json(self, 400, {"error": "topics_not_enabled"})
            return False
        if topic_id is not None:
            topic = self._run_async(self.store.get_topic(chat_id, topic_id))
            if not topic:
                _json(self, 404, {"error": "topic_not_found"})
                return False
            if require_active and not bool(topic.get("is_active", True)):
                _json(self, 409, {"error": "topic_inactive"})
                return False
        return True

    def _require_read(self):
        return self._require_permission("read")

    def _require_moderate(self):
        return self._require_permission("moderate")

    def _protected(self):
        if self._rate_limited(self):
            _json(self, 429, {"error": "rate_limited"})
            return False
        if not self._origin_allowed():
            _json(self, 403, {"error": "origin_not_allowed"})
            return False
        if not self._authorized():
            _json(self, 401, {"error": "unauthorized"})
            return False
        if not self._proxy_identity_valid():
            _json(self, 401, {"error": "invalid_proxy_identity"})
            return False
        return True

    def do_GET(self):
        self._obs_started = time.monotonic()
        _obs_token = set_request_id(new_request_id("http"))
        self._obs_token = _obs_token
        OBSERVABILITY.emit("http_request", method="GET", path=urlparse(self.path).path)
        parsed = urlparse(self.path)
        path = parsed.path

        if self._serve_dashboard():
            return
        if self._local_dashboard_proxy():
            return

        if path == "/health":
            return _json(self, 200, {
                "ok": True,
                "service": "ghostea",
                "status": "running",
            })

        if not self._protected():
            return

        try:
            # Authentication/identity is delegated from the Vercel session proxy.
            if path == "/api/auth/me":
                role = self.headers.get("X-Ghostea-Role", "")
                admin_id = self.headers.get("X-Ghostea-Admin-Id", "")
                current = None
                if self.admins and admin_id.isdigit():
                    try:
                        current = self._run_async(self.admins.authorize(admin_id, role))
                    except Exception:
                        current = None
                if not current:
                    return _json(self, 401, {"error": "session_not_active"})
                return _json(self, 200, {
                    "authenticated": True,
                    "admin": current,
                })

            if path == "/api/auth/admins":
                if not self._require_permission("manage_admins"):
                    return
                rows = self._run_async(self.admins.list_admins())
                return _json(self, 200, {"admins": rows})

            if path == "/api/diagnostics":
                if not self._require_permission("read"):
                    return
                limit = 100
                try:
                    limit = max(1, min(int(parse_qs(parsed.query).get("limit", ["100"])[0]), 200))
                except (TypeError, ValueError):
                    pass
                return _json(self, 200, {
                    "ok": True,
                    "service": "ghostea",
                    "observability": OBSERVABILITY.snapshot(limit),
                })

            if path == "/api/health":
                required_tables = [
                    "ghostea_chat_registry",
                    "ghostea_group_settings",
                    "ghostea_topic_registry",
                    "ghostea_upload_sessions",
                    "ghostea_resources",
                    "ghostea_schema_meta",
                ]
                table_status = self._call_sync(
                    self.store.db.check_tables,
                    required_tables,
                )
                schema_ok = all(table_status.values())
                readiness = getattr(self.server, "production_readiness", {})
                return _json(self, 200 if schema_ok else 503, {
                    "ok": schema_ok,
                    "service": "ghostea",
                    "database": schema_ok,
                    "schema": {
                        "version": 9 if table_status.get("ghostea_schema_meta") else None,
                        "tables": table_status,
                    },
                    "production_ready": bool(readiness.get("ready", True)) and schema_ok,
                })

            if path == "/api/groups":
                if not self._require_read(): return
                cache_key = f"groups:{self.headers.get('X-Ghostea-Admin-Id','')}"
                cached = self._cached_json(cache_key)
                if cached is not None:
                    return _json(self, 200, cached)
                rows = self._call_sync(
                    self.store.db.select,
                    "ghostea_group_settings",
                    {"select": "*", "order": "updated_at.desc", "limit": "200"},
                )
                # Phase 8 dashboard needs chat capabilities alongside settings.
                # Registry is additive; if an older deployment has not populated
                # it yet, settings-only rows remain fully usable.
                try:
                    registry = self._call_sync(
                        self.store.db.select,
                        "ghostea_chat_registry",
                        {"select": "chat_id,chat_type,title,username,visibility,is_forum,is_linked", "limit": "200"},
                    )
                except Exception:
                    registry = []
                meta = {str(r.get("chat_id")): r for r in registry}
                merged = []
                for row in rows:
                    item = dict(row)
                    info = meta.get(str(row.get("chat_id")))
                    if info and info.get("is_linked") is False:
                        continue
                    if info:
                        for key in ("chat_type", "title", "username", "visibility", "is_forum"):
                            item[key] = info.get(key)
                    else:
                        item.setdefault("chat_type", "supergroup")
                        item.setdefault("visibility", "private")
                        item.setdefault("is_forum", False)
                    registry_row = {
                        "chat_id": item.get("chat_id"),
                        "chat_type": item.get("chat_type"),
                        "title": item.get("title"),
                        "username": item.get("username"),
                        "visibility": item.get("visibility"),
                        "is_forum": item.get("is_forum"),
                    }
                    caps = capabilities_from_registry(registry_row)
                    visibility = visibility_from_registry(registry_row)
                    item["visibility"] = visibility.visibility
                    item["username"] = visibility.username
                    item["public_url"] = visibility.public_url
                    item["access_label"] = visibility.access_label
                    item["visibility_info"] = visibility.as_dict()
                    item["capabilities"] = caps.as_dict()
                    item["forum_compatibility"] = resolve_forum_compatibility(caps).as_dict()
                    merged.append(item)
                return _json(self, 200, self._put_cache(cache_key, {"groups": merged}))

            if path.startswith("/api/groups/") and path.endswith("/topics"):
                if not self._require_read(): return
                parts = path.split("/")
                if len(parts) != 5:
                    return _json(self, 404, {"error": "not_found"})
                chat_id = int(parts[3])
                if not self._require_forum_topic(chat_id): return
                params = parse_qs(parsed.query)
                include_inactive = params.get("include_inactive", ["false"])[0].lower() == "true"
                limit = max(1, min(int(params.get("limit", ["200"])[0]), 500))
                topics = self._run_async(self.store.list_topics(chat_id, include_inactive=include_inactive, limit=limit))
                return _json(self, 200, {"topics": topics})

            if path.startswith("/api/groups/") and "/topics/" in path and path.endswith("/settings"):
                if not self._require_read(): return
                parts = path.split("/")
                if len(parts) != 7 or parts[4] != "topics" or parts[6] != "settings":
                    return _json(self, 404, {"error": "not_found"})
                chat_id = int(parts[3]); topic_id = int(parts[5])
                if not self._require_forum_topic(chat_id, topic_id, require_active=False): return
                overrides = self._run_async(self.store.get_topic_settings(chat_id, topic_id))
                effective = self._run_async(self.store.get_effective_settings(chat_id, topic_id))
                return _json(self, 200, {"chat_id": chat_id, "topic_id": topic_id, "overrides": overrides, "effective": effective})

            if path.startswith("/api/groups/") and path.endswith("/analytics"):
                if not self._require_read(): return
                parts = path.split("/")
                if len(parts) != 5:
                    return _json(self, 404, {"error": "not_found"})
                chat_id = int(parts[3])
                params = parse_qs(parsed.query)
                days = int(params.get("days", ["7"])[0])
                days = max(1, min(days, 90))
                topic_raw = params.get("topic_id", [None])[0]
                topic_id = int(topic_raw) if topic_raw not in (None, "") else None
                if topic_id is not None and not self._require_forum_topic(chat_id, topic_id, require_active=False): return
                report = self._run_async(
                    self.analytics.report(chat_id, days, topic_id=topic_id)
                )
                return _json(self, 200, report)

            if path.startswith("/api/groups/") and path.endswith("/risk"):
                if not self._require_read(): return
                parts = path.split("/")
                if len(parts) != 5:
                    return _json(self, 404, {"error": "not_found"})
                chat_id = int(parts[3])
                params = parse_qs(parsed.query)
                days = int(params.get("days", ["7"])[0])
                days = max(1, min(days, 90))
                topic_raw = params.get("topic_id", [None])[0]
                topic_id = int(topic_raw) if topic_raw not in (None, "") else None
                if topic_id is not None and not self._require_forum_topic(chat_id, topic_id, require_active=False): return
                if self.risk is None:
                    return _json(self, 503, {"error": "risk_unavailable"})
                cache_key = f"risk:{chat_id}:{days}:{topic_id}"
                cached = self._cached_json(cache_key)
                if cached is not None:
                    return _json(self, 200, cached)
                try:
                    report = self._run_async(
                        self.risk.report(chat_id, days=days, limit=50, topic_id=topic_id)
                    )
                except RuntimeError as error:
                    if str(error) == "risk_data_unavailable":
                        return _json(self, 503, {"error": "risk_data_unavailable"})
                    raise
                return _json(self, 200, self._put_cache(cache_key, report))

            if path.startswith("/api/groups/") and path.endswith("/users"):
                if not self._require_read(): return
                parts = path.split("/")
                if len(parts) != 5:
                    return _json(self, 404, {"error": "not_found"})
                chat_id = int(parts[3])
                limit = int(parse_qs(parsed.query).get("limit", ["100"])[0])
                limit = max(1, min(limit, 500))
                cache_key = f"users:{chat_id}:{limit}"
                cached = self._cached_json(cache_key)
                if cached is not None:
                    return _json(self, 200, cached)
                users = self._run_async(
                    self.store.get_user_directory(chat_id, limit)
                )
                return _json(self, 200, self._put_cache(cache_key, {"users": users}))

            if path.startswith("/api/groups/") and "/users/" in path and path.endswith("/profile"):
                if not self._require_read(): return
                parts = path.split("/")
                # /api/groups/<chat_id>/users/<user_id>/profile
                # has 7 segments after split() because of the leading slash.
                if len(parts) != 7 or parts[4] != "users" or parts[6] != "profile":
                    return _json(self, 404, {"error": "not_found"})
                chat_id = int(parts[3])
                user_id = int(parts[5])
                profile = self.user_management._run_profile(chat_id, user_id)
                if self.risk is not None:
                    try:
                        profile["risk"] = self._run_async(
                            self.risk.user(chat_id, user_id, days=30)
                        )
                    except Exception:
                        # Risk is advisory; a risk-query outage must not make
                        # the underlying user profile unusable.
                        profile["risk"] = None
                return _json(self, 200, profile)

            if path.startswith("/api/groups/") and path.endswith("/settings"):
                if not self._require_read(): return
                parts = path.split("/")
                if len(parts) != 5:
                    return _json(self, 404, {"error": "not_found"})
                chat_id = int(parts[3])
                settings = self._call_sync(
                    self.store.db.select,
                    "ghostea_group_settings",
                    {"chat_id": f"eq.{chat_id}", "limit": "1"},
                )
                return _json(self, 200, settings[0] if settings else {})

            if path.startswith("/api/groups/") and path.endswith("/logs"):
                if not self._require_read(): return
                parts = path.split("/")
                if len(parts) != 5:
                    return _json(self, 404, {"error": "not_found"})
                chat_id = int(parts[3])
                params = parse_qs(parsed.query)
                limit = int(params.get("limit", ["100"])[0])
                limit = max(1, min(limit, 200))
                topic_raw = params.get("topic_id", [None])[0]
                topic_id = int(topic_raw) if topic_raw not in (None, "") else None
                if topic_id is not None and not self._require_forum_topic(chat_id, topic_id, require_active=False): return
                query = {
                    "chat_id": f"eq.{chat_id}",
                    "order": "created_at.desc",
                    "limit": str(limit),
                }
                if topic_id is not None:
                    query["topic_id"] = f"eq.{topic_id}"
                logs = self._call_sync(
                    self.store.db.select,
                    "ghostea_moderation_logs",
                    query,
                )
                return _json(self, 200, {"logs": logs})

            if path.startswith("/api/groups/") and path.endswith("/resources"):
                if not self._require_read(): return
                parts = path.split("/")
                if len(parts) != 5:
                    return _json(self, 404, {"error": "not_found"})
                chat_id = int(parts[3])
                params = parse_qs(parsed.query)
                limit = max(1, min(int(params.get("limit", ["100"])[0]), 200))
                topic_raw = params.get("topic_id", [None])[0]
                topic_id = int(topic_raw) if topic_raw not in (None, "") else None
                if topic_id is not None and not self._require_forum_topic(chat_id, topic_id, require_active=False):
                    return
                query = {
                    "chat_id": f"eq.{chat_id}",
                    "order": "created_at.desc",
                    "limit": str(limit),
                }
                if topic_id is not None:
                    query["topic_id"] = f"eq.{topic_id}"
                rows = self._call_sync(
                    self.store.db.select,
                    "ghostea_resources",
                    query,
                )
                counts = {
                    "total": len(rows),
                    "files": sum(1 for r in rows if r.get("source_kind") != "url" and r.get("mode") != "flag"),
                    "urls": sum(1 for r in rows if r.get("source_kind") == "url"),
                    "flags": sum(1 for r in rows if r.get("mode") == "flag"),
                }
                return _json(self, 200, {
                    "resources": rows,
                    "counts": counts,
                    "limit": limit,
                    "topic_id": topic_id,
                })

            if path.startswith("/api/groups/") and path.endswith("/filters"):
                if not self._require_read(): return
                parts = path.split("/")
                if len(parts) != 5:
                    return _json(self, 404, {"error": "not_found"})
                chat_id = int(parts[3])
                filters = self._call_sync(
                    self.store.db.select,
                    "ghostea_custom_filters",
                    {"chat_id": f"eq.{chat_id}", "order": "created_at.asc", "limit": "500"},
                )
                return _json(self, 200, {"filters": filters})
        except (ValueError, TypeError):
            return _json(self, 400, {"error": "invalid_request"})
        except Exception:
            # Do not leak Supabase/network internals through the public API.
            return _json(self, 500, {"error": "internal_server_error"})

        return _json(self, 404, {"error": "not_found"})

    def do_POST(self):
        self._obs_started = time.monotonic()
        _obs_token = set_request_id(new_request_id("http"))
        self._obs_token = _obs_token
        OBSERVABILITY.emit("http_request", method="POST", path=urlparse(self.path).path)
        parsed = urlparse(self.path)

        if self._telegram_webhook():
            return

        if self._local_dashboard_proxy():
            return

        # Vercel authenticates against this server-to-server endpoint.
        if parsed.path == "/api/auth/login":
            if self._rate_limited(self):
                return _json(self, 429, {"error": "rate_limited"})
            if not self._authorized() or not self._origin_allowed():
                return _json(self, 401, {"error": "unauthorized"})
            if not os.getenv("GHOSTEA_PROXY_SIGNING_SECRET", "").strip():
                return _json(self, 500, {"error": "server_not_configured"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > MAX_BODY_BYTES:
                    return _json(self, 413, {"error": "payload_too_large"})
                payload = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(payload, dict):
                    return _json(self, 400, {"error": "object_required"})
                admin = self.admins and self._run_async(
                    self.admins.authenticate(
                        payload.get("username"), payload.get("password")
                    )
                )
                if not admin:
                    return _json(self, 401, {"error": "invalid_credentials"})
                return _json(self, 200, {"ok": True, "admin": admin})
            except json.JSONDecodeError:
                return _json(self, 400, {"error": "invalid_json"})
            except Exception:
                return _json(self, 500, {"error": "internal_server_error"})

        if not self._protected():
            return
        parts = parsed.path.split("/")
        if parsed.path == "/api/groups/link":
            if not self._require_permission("settings"):
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > MAX_BODY_BYTES:
                    return _json(self, 413, {"error": "payload_too_large"})
                if not self.headers.get("Content-Type", "").startswith("application/json"):
                    return _json(self, 415, {"error": "json_required"})
                payload = json.loads(self.rfile.read(length) or b"{}")
                chat_id = int(str(payload.get("chat_id", "")).strip())
                if chat_id == 0 or abs(chat_id) > 2**52:
                    return _json(self, 400, {"error": "invalid_chat_id"})
                result = self._verify_and_link_group(
                    chat_id,
                    self.headers.get("X-Ghostea-Admin-Id", ""),
                )
                return _json(self, 201, result)
            except PermissionError as error:
                code = str(error)
                if code == "bot_not_in_group":
                    return _json(self, 409, {"error": "bot_not_in_group"})
                if code == "bot_not_admin":
                    return _json(self, 409, {"error": "bot_not_admin"})
                if code in {"telegram_bot_identity_unverifiable", "telegram_bot_membership_unverifiable"}:
                    return _json(self, 502, {"error": code})
                return _json(self, 403, {"error": "link_denied"})
            except ValueError as error:
                msg = str(error)
                if msg == "unsupported_chat_type":
                    return _json(self, 400, {"error": msg})
                if msg == "telegram_chat_not_found":
                    return _json(self, 404, {"error": msg})
                return _json(self, 400, {"error": "invalid_chat_id"})
            except Exception as error:
                # Keep the public response safe, but make the failure useful
                # in Render logs instead of silently hiding the Telegram cause.
                self.log_message("Telegram group link verification failed: %s", error)
                return _json(self, 502, {"error": "telegram_link_verification_failed"})

        if parsed.path == "/api/auth/admins":
            if not self._require_permission("manage_admins"):
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > MAX_BODY_BYTES:
                    return _json(self, 413, {"error": "payload_too_large"})
                payload = json.loads(self.rfile.read(length) or b"{}")
                admin = self._run_async(
                    self.admins.create(
                        payload.get("username"),
                        payload.get("password"),
                        payload.get("role"),
                        payload.get("display_name", ""),
                    )
                )
                self._invalidate_cache()
                return _json(self, 201, {"admin": admin})
            except ValueError as e:
                return _json(self, 400, {"error": str(e)})
            except json.JSONDecodeError:
                return _json(self, 400, {"error": "invalid_json"})
            except Exception:
                return _json(self, 500, {"error": "internal_server_error"})

        if len(parts) == 5 and parts[1] == "api" and parts[2] == "groups" and parts[4] == "users":
            if not self._require_permission("moderate"):
                return
            try:
                chat_id = int(parts[3])
                length = int(self.headers.get("Content-Length", "0"))
                if length < 0 or length > MAX_BODY_BYTES:
                    return _json(self, 413, {"error": "payload_too_large"})
                if not self.headers.get("Content-Type", "").startswith("application/json"):
                    return _json(self, 415, {"error": "json_required"})
                payload = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(payload, dict):
                    return _json(self, 400, {"error": "object_required"})

                target_user_id = int(payload.get("user_id"))
                action = str(payload.get("action", "")).lower()
                reason = str(payload.get("reason", "Dashboard action")).strip()[:500]
                minutes = int(payload.get("minutes", 10))

                if target_user_id == 0:
                    return _json(self, 400, {"error": "invalid_user_id"})
                if action not in {
                    "warn", "unwarn", "reset_warnings",
                    "ban", "unban", "mute", "unmute",
                }:
                    return _json(self, 400, {"error": "invalid_action"})
                if action == "mute" and not 1 <= minutes <= 10080:
                    return _json(self, 400, {"error": "invalid_minutes"})

                current_admin_id = int(self.headers.get("X-Ghostea-Admin-Id", "0") or 0)

                # The Vercel proxy authenticates the dashboard. The Telegram
                # bot itself remains the executor of moderation actions, while
                # the real dashboard admin is retained in the audit trail.
                if action == "warn":
                    result = self.user_management._run_action(
                        "warn", chat_id, target_user_id, admin_id=current_admin_id, reason=reason
                    )
                elif action == "unwarn":
                    result = self.user_management._run_action(
                        "unwarn", chat_id, target_user_id, admin_id=current_admin_id
                    )
                elif action == "reset_warnings":
                    result = self.user_management._run_action(
                        "reset_warnings", chat_id, target_user_id, admin_id=current_admin_id
                    )
                elif action == "ban":
                    result = self.user_management._run_action(
                        "ban", chat_id, target_user_id, admin_id=current_admin_id
                    )
                elif action == "unban":
                    result = self.user_management._run_action(
                        "unban", chat_id, target_user_id, admin_id=current_admin_id
                    )
                elif action == "mute":
                    result = self.user_management._run_action(
                        "mute", chat_id, target_user_id, admin_id=current_admin_id, minutes=minutes
                    )
                else:
                    result = self.user_management._run_action(
                        "unmute", chat_id, target_user_id, admin_id=current_admin_id
                    )
                self._invalidate_cache(f"groups:{current_admin_id}")
                return _json(self, 200, result)
            except PermissionError as error:
                message = str(error)
                if message == "target_lookup_failed":
                    return _json(self, 503, {"error": "target_lookup_failed", "retryable": True})
                if message == "target_is_admin":
                    return _json(self, 403, {"error": "target_is_admin", "retryable": False})
                if message.startswith("missing_bot_permission:"):
                    return _json(self, 503, {"error": "bot_permission_unavailable", "retryable": True})
                if message.startswith(("mute_failed:", "ban_failed:", "unmute_failed:", "unban_failed:")):
                    return _json(self, 502, {"error": "telegram_action_failed", "detail": message.split(":", 1)[1], "retryable": False})
                if message == "member_restriction_not_supported_for_basic_group":
                    return _json(self, 409, {"error": message, "retryable": False})
                return _json(self, 502, {"error": "telegram_action_failed", "retryable": False})
            except (ValueError, TypeError):
                return _json(self, 400, {"error": "invalid_request"})
            except Exception:
                return _json(self, 500, {"error": "internal_server_error"})

        parts = parsed.path.split("/")
        if len(parts) != 5 or parts[1] != "api" or parts[2] != "groups" or parts[4] != "filters":
            return _json(self, 404, {"error": "not_found"})
        if not self._require_permission("settings"):
            return
        try:
            chat_id = int(parts[3])
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > MAX_BODY_BYTES:
                return _json(self, 413, {"error": "payload_too_large"})
            if not self.headers.get("Content-Type", "").startswith("application/json"):
                return _json(self, 415, {"error": "json_required"})
            payload = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(payload, dict):
                return _json(self, 400, {"error": "object_required"})
            filter_type = payload.get("filter_type")
            value = payload.get("value")
            if filter_type not in ("word", "domain", "pattern"):
                return _json(self, 400, {"error": "invalid_filter_type"})
            if not isinstance(value, str) or not _validate_filter_value(filter_type, value):
                return _json(self, 400, {"error": "invalid_filter_value"})
            result = self._run_async(
                self.store.add_custom_filter(chat_id, filter_type, value.strip())
            )
            return _json(self, 200, result)
        except json.JSONDecodeError:
            return _json(self, 400, {"error": "invalid_json"})
        except (ValueError, TypeError):
            return _json(self, 400, {"error": "invalid_request"})
        except Exception:
            return _json(self, 500, {"error": "internal_server_error"})

    def do_DELETE(self):
        self._obs_started = time.monotonic()
        _obs_token = set_request_id(new_request_id("http"))
        self._obs_token = _obs_token
        OBSERVABILITY.emit("http_request", method="DELETE", path=urlparse(self.path).path)
        if self._local_dashboard_proxy():
            return
        if not self._protected():
            return
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/auth/admins/"):
            if not self._require_permission("manage_admins"):
                return
            try:
                admin_id = int(parsed.path.split("/")[-1])
                current_admin_id = int(self.headers.get("X-Ghostea-Admin-Id", "0") or 0)
                if admin_id == current_admin_id:
                    return _json(self, 400, {"error": "cannot_delete_current_admin"})
                result = self._run_async(self.admins.delete(admin_id))
                return _json(self, 200, result)
            except ValueError as e:
                return _json(self, 400, {"error": str(e)})
            except Exception:
                return _json(self, 500, {"error": "internal_server_error"})

        parts = parsed.path.split("/")
        if len(parts) != 6 or parts[1] != "api" or parts[2] != "groups" or parts[4] != "filters":
            return _json(self, 404, {"error": "not_found"})
        if not self._require_permission("settings"):
            return
        try:
            chat_id = int(parts[3])
            filter_id = int(parts[5])
            result = self._run_async(
                self.store.remove_custom_filter_by_id(chat_id, filter_id)
            )
            self._invalidate_cache("groups:")
            return _json(self, 200, {"ok": True, "deleted": len(result or [])})
        except (ValueError, TypeError):
            return _json(self, 400, {"error": "invalid_request"})
        except Exception:
            return _json(self, 500, {"error": "internal_server_error"})

    def do_PATCH(self):
        self._obs_started = time.monotonic()
        _obs_token = set_request_id(new_request_id("http"))
        self._obs_token = _obs_token
        OBSERVABILITY.emit("http_request", method="PATCH", path=urlparse(self.path).path)
        if self._local_dashboard_proxy():
            return
        if not self._protected():
            return

        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/auth/admins/"):
            if not self._require_permission("manage_admins"):
                return
            try:
                admin_id = int(parsed.path.split("/")[-1])
                current_admin_id = int(self.headers.get("X-Ghostea-Admin-Id", "0") or 0)
                if admin_id == current_admin_id:
                    return _json(self, 400, {"error": "cannot_modify_current_admin"})
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > MAX_BODY_BYTES:
                    return _json(self, 413, {"error": "payload_too_large"})
                payload = json.loads(self.rfile.read(length) or b"{}")
                result = self._run_async(self.admins.update(admin_id, payload))
                self._invalidate_cache()
                return _json(self, 200, {"admin": result})
            except ValueError as e:
                return _json(self, 400, {"error": str(e)})
            except json.JSONDecodeError:
                return _json(self, 400, {"error": "invalid_json"})
            except Exception:
                return _json(self, 500, {"error": "internal_server_error"})

        topic_match = re.match(r"^/api/groups/(-?\d+)/topics/(-?\d+)/settings$", parsed.path)
        if topic_match:
            if not self._require_permission("settings"):
                return
            try:
                chat_id = int(topic_match.group(1)); topic_id = int(topic_match.group(2))
                if not self._require_forum_topic(chat_id, topic_id, require_active=False): return
                length = int(self.headers.get("Content-Length", "0"))
                if length < 0 or length > MAX_BODY_BYTES:
                    return _json(self, 413, {"error": "payload_too_large"})
                if not self.headers.get("Content-Type", "").startswith("application/json"):
                    return _json(self, 415, {"error": "json_required"})
                payload = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(payload, dict):
                    return _json(self, 400, {"error": "object_required"})
                # Empty object is a no-op; explicit reset uses {"clear": true}
                if payload.get("clear") is True:
                    result = self._run_async(self.store.clear_topic_settings(chat_id, topic_id))
                else:
                    changes = {k:v for k,v in payload.items() if k != "clear"}
                    result = self._run_async(self.store.update_topic_settings(chat_id, topic_id, changes))
                self._invalidate_cache("groups:")
                return _json(self, 200, {"chat_id": chat_id, "topic_id": topic_id, "overrides": result})
            except ValueError as e:
                return _json(self, 400, {"error": str(e)})
            except json.JSONDecodeError:
                return _json(self, 400, {"error": "invalid_json"})
            except Exception:
                return _json(self, 500, {"error": "internal_server_error"})

        if not (
            parsed.path.startswith("/api/groups/")
            and parsed.path.endswith("/settings")
        ):
            return _json(self, 404, {"error": "not_found"})

        if not self._require_permission("settings"):
            return

        try:
            parts = parsed.path.split("/")
            if len(parts) != 5:
                return _json(self, 404, {"error": "not_found"})
            chat_id = int(parts[3])

            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > MAX_BODY_BYTES:
                return _json(self, 413, {"error": "payload_too_large"})

            content_type = self.headers.get("Content-Type", "")
            if not content_type.startswith("application/json"):
                return _json(self, 415, {"error": "json_required"})

            payload = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(payload, dict):
                return _json(self, 400, {"error": "object_required"})

            allowed = {
                "max_warnings", "mute1_minutes", "mute2_minutes",
                "flood_window_seconds", "flood_message_limit",
                "flood_mute_minutes", "blocked_link_action",
                "abuse_filter_enabled", "spam_filter_enabled",
                "link_filter_enabled", "flood_protection_enabled",
                "welcome_enabled", "antiraid_enabled",
                "antiraid_join_limit", "antiraid_window_seconds",
                "antiraid_lock_minutes", "verification_enabled",
                "verification_timeout_seconds", "max_message_length",
                "repeated_message_window_seconds", "repeated_message_limit",
                "mention_spam_limit", "warning_decay_enabled",
                "warning_decay_days", "auto_cleanup_enabled",
                "cleanup_max_age_days",
            }
            changes = {k: v for k, v in payload.items() if k in allowed}
            if not changes:
                return _json(self, 400, {"error": "no_supported_settings"})

            # Strict validation prevents the dashboard from writing malformed
            # values that could later crash message processing.
            integer_ranges = {
                "max_warnings": (1, 20),
                "mute1_minutes": (1, 10080),
                "mute2_minutes": (1, 10080),
                "flood_window_seconds": (1, 300),
                "flood_message_limit": (2, 100),
                "flood_mute_minutes": (1, 10080),
                "antiraid_join_limit": (2, 1000),
                "antiraid_window_seconds": (5, 3600),
                "antiraid_lock_minutes": (1, 1440),
                "verification_timeout_seconds": (30, 3600),
                "max_message_length": (100, 10000),
                "repeated_message_window_seconds": (5, 3600),
                "repeated_message_limit": (2, 100),
                "mention_spam_limit": (2, 100),
                "warning_decay_days": (1, 3650),
                "cleanup_max_age_days": (1, 3650),
            }
            for key, (low, high) in integer_ranges.items():
                if key in changes:
                    if isinstance(changes[key], bool) or not isinstance(changes[key], int):
                        return _json(self, 400, {"error": f"invalid_{key}"})
                    if not low <= changes[key] <= high:
                        return _json(self, 400, {"error": f"invalid_{key}"})

            for key in (
                "abuse_filter_enabled", "spam_filter_enabled",
                "link_filter_enabled", "flood_protection_enabled",
                "welcome_enabled", "antiraid_enabled",
                "verification_enabled", "warning_decay_enabled",
                "auto_cleanup_enabled",
            ):
                if key in changes and not isinstance(changes[key], bool):
                    return _json(self, 400, {"error": f"invalid_{key}"})

            if "blocked_link_action" in changes and changes["blocked_link_action"] not in ("delete", "warn"):
                return _json(self, 400, {"error": "invalid_blocked_link_action"})

            # Route through the store so the bot's short-lived settings cache
            # is invalidated immediately after a dashboard update.
            result = self._run_async(self.store.update_settings(chat_id, changes))
            self._invalidate_cache("groups:")
            return _json(self, 200, result)
        except json.JSONDecodeError:
            return _json(self, 400, {"error": "invalid_json"})
        except (ValueError, TypeError):
            return _json(self, 400, {"error": "invalid_request"})
        except Exception:
            return _json(self, 500, {"error": "internal_server_error"})


def start_web_server(store, analytics, bot=None, risk=None, admins=None, loop=None, production_readiness=None, permission_service=None, telegram_update_callback=None):
    from ghostea.config import PORT
    port = PORT
    DashboardHandler.store = store
    DashboardHandler.analytics = analytics
    DashboardHandler.risk = risk
    DashboardHandler.admins = admins
    DashboardHandler.user_management = None
    DashboardHandler.permission_service = permission_service
    DashboardHandler._async_loop = loop
    DashboardHandler.telegram_update_callback = telegram_update_callback

    server = ThreadingHTTPServer(("0.0.0.0", port), DashboardHandler)
    server.production_readiness = production_readiness or {}
    server.daemon_threads = True
    server.request_queue_size = 64

    def run_async(coro):
        active_loop = loop
        if active_loop is not None and active_loop.is_running():
            future = asyncio.run_coroutine_threadsafe(coro, active_loop)
            return future.result(timeout=45)
        return asyncio.run(coro)

    if bot is not None:
        from ghostea.services.user_management_service import UserManagementService

        manager = UserManagementService(store, bot, permission_service=permission_service)

        async def _profile(chat_id, user_id):
            return await manager.profile(chat_id, user_id)

        async def _action(action, chat_id, user_id, admin_id=0, **kwargs):
            if action == "warn":
                return await manager.warn(chat_id, user_id, admin_id, kwargs.get("reason", "Dashboard action"))
            if action == "unwarn":
                return await manager.remove_warning(chat_id, user_id, admin_id)
            if action == "reset_warnings":
                return await manager.reset_warnings(chat_id, user_id, admin_id)
            if action == "ban":
                return await manager.ban(chat_id, user_id, admin_id)
            if action == "unban":
                return await manager.unban(chat_id, user_id, admin_id)
            if action == "mute":
                return await manager.mute(chat_id, user_id, admin_id, kwargs.get("minutes", 10))
            if action == "unmute":
                return await manager.unmute(chat_id, user_id, admin_id)
            raise ValueError("invalid_action")

        manager._run_profile = lambda chat_id, user_id: run_async(_profile(chat_id, user_id))
        manager._run_action = lambda action, chat_id, user_id, **kwargs: run_async(
            _action(action, chat_id, user_id, **kwargs)
        )
        DashboardHandler.user_management = manager

    thread = threading.Thread(
        target=server.serve_forever,
        name="ghostea-web",
        daemon=True,
    )
    thread.start()
    return server
