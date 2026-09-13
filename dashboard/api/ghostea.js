import crypto from "node:crypto";

const SESSION_TTL = 8 * 60 * 60;
const ALLOWED_GET = new Set(["/api/health", "/api/groups"]);
const LOGIN_WINDOW_MS = 60 * 1000;
const LOGIN_MAX_ATTEMPTS = 10;
const MIN_SECRET_LENGTH = 32;
const loginAttempts = new Map();

function secret(name) {
  return (process.env[name] || "").trim();
}

function proxySign(value) {
  const key = secret("GHOSTEA_PROXY_SIGNING_SECRET");
  if (!key) return "";
  return crypto.createHmac("sha256", key).update(value).digest("base64url");
}

function sign(value) {
  return crypto.createHmac("sha256", secret("GHOSTEA_SESSION_SECRET"))
    .update(value)
    .digest("base64url");
}

function makeSession(admin) {
  const payload = [
    Date.now(),
    crypto.randomBytes(18).toString("base64url"),
    admin.id,
    admin.role,
    admin.username
  ].join(":");
  return `${Buffer.from(payload).toString("base64url")}.${sign(payload)}`;
}

function validSession(req) {
  const cookie = req.headers.cookie || "";
  const match = cookie.match(/(?:^|;\s*)ghostea_session=([^;]+)/);
  if (!match || !secret("GHOSTEA_SESSION_SECRET")) return null;

  const raw = match[1];
  const parts = raw.split(".");
  if (parts.length !== 2) return null;

  let payload;
  try {
    payload = Buffer.from(parts[0], "base64url").toString("utf8");
  } catch {
    return null;
  }

  const fields = payload.split(":");
  const issuedAt = Number(fields[0]);
  const age = Date.now() - issuedAt;
  if (!Number.isFinite(issuedAt) || age < 0 || age > SESSION_TTL * 1000) {
    return null;
  }
  if (!fields[2] || !fields[3] || !fields[4]) return null;

  const expected = sign(payload);
  const actual = parts[1];
  if (expected.length !== actual.length) return null;

  if (!crypto.timingSafeEqual(Buffer.from(expected), Buffer.from(actual))) {
    return null;
  }

  return {
    admin_id: fields[2],
    role: fields[3],
    username: fields.slice(4).join(":"),
  };
}

function json(res, status, body, extra = {}) {
  res.status(status).setHeader("Content-Type", "application/json");
  res.setHeader("Cache-Control", "no-store");
  res.setHeader("X-Content-Type-Options", "nosniff");
  res.setHeader("Referrer-Policy", "no-referrer");
  res.setHeader("X-Frame-Options", "DENY");
  res.setHeader("Permissions-Policy", "camera=(), microphone=(), geolocation=()");
  res.setHeader("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'; base-uri 'none'");
  Object.entries(extra).forEach(([k, v]) => res.setHeader(k, v));
  return res.end(JSON.stringify(body));
}

function parseBody(req) {
  return new Promise((resolve, reject) => {
    let raw = "";
    let size = 0;
    req.on("data", chunk => {
      size += chunk.length;
      if (size > 16 * 1024) {
        reject(new Error("payload_too_large"));
        req.destroy();
        return;
      }
      raw += chunk;
    });
    req.on("end", () => {
      try { resolve(raw ? JSON.parse(raw) : {}); }
      catch { reject(new Error("invalid_json")); }
    });
    req.on("error", reject);
  });
}

export default async function handler(req, res) {
  const target = secret("GHOSTEA_API_URL").replace(/\/+$/, "");
  if (!target || !secret("GHOSTEA_API_KEY")) {
    return json(res, 500, { error: "server_not_configured" });
  }

  // Local session probe: determine browser auth state without probing the protected upstream API.
  // This avoids expected 401 entries on every dashboard page load.
  if (req.method === "GET" && req.query.action === "session") {
    const session = validSession(req);
    return json(res, 200, session
      ? { authenticated: true, admin: session }
      : { authenticated: false });
  }

  if (req.method === "POST" && req.query.action === "login") {
    if (secret("GHOSTEA_SESSION_SECRET").length < MIN_SECRET_LENGTH) {
      return json(res, 500, { error: "server_not_configured" });
    }
    const ip = String(req.headers["x-forwarded-for"] || req.headers["x-real-ip"] || "unknown").split(",")[0].trim().slice(0, 128);
    const now = Date.now();
    const attempts = (loginAttempts.get(ip) || []).filter(ts => now - ts < LOGIN_WINDOW_MS);
    if (attempts.length >= LOGIN_MAX_ATTEMPTS) {
      loginAttempts.set(ip, attempts);
      return json(res, 429, { error: "rate_limited" }, { "Retry-After": "60" });
    }
    attempts.push(now);
    loginAttempts.set(ip, attempts);
    if (loginAttempts.size > 4096) {
      for (const [key, values] of loginAttempts) {
        if (!values.length || now - values[values.length - 1] >= LOGIN_WINDOW_MS) loginAttempts.delete(key);
      }
    }

    const body = await parseBody(req).catch(() => null);
    if (!body || typeof body.username !== "string" || typeof body.password !== "string") {
      return json(res, 400, { error: "credentials_required" });
    }

    try {
      const upstream = await fetch(`${target}/api/auth/login`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${secret("GHOSTEA_API_KEY")}`,
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        body: JSON.stringify({
          username: body.username,
          password: body.password,
        }),
        redirect: "error",
      });
      const result = await upstream.json().catch(() => null);
      if (!upstream.ok || !result?.admin) {
        return json(res, upstream.status || 401, {
          error: result?.error || "invalid_credentials"
        });
      }

      const session = makeSession(result.admin);
      res.setHeader(
        "Set-Cookie",
        `ghostea_session=${session}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=${SESSION_TTL}`
      );
      return json(res, 200, { ok: true, admin: result.admin });
    } catch {
      return json(res, 502, { error: "ghostea_unreachable" });
    }
  }

  if (req.method === "POST" && req.query.action === "logout") {
    res.setHeader(
      "Set-Cookie",
      "ghostea_session=; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=0"
    );
    return json(res, 200, { ok: true });
  }

  const session = validSession(req);
  if (!session) {
    return json(res, 401, { error: "login_required" });
  }

  const requested = typeof req.query.path === "string" ? req.query.path : "";
  if (!requested.startsWith("/api/")) {
    return json(res, 400, { error: "invalid_path" });
  }

  // Parse the requested path separately from its query string so analytics
  // requests such as /api/groups/<id>/analytics?days=30 remain allowlisted.
  let parsedPath;
  try {
    parsedPath = new URL(requested, target);
  } catch {
    return json(res, 400, { error: "invalid_path" });
  }

  const pathname = parsedPath.pathname;
  const match = pathname.match(/^\/api\/groups\/(-?\d+)\/(settings|analytics|logs|filters|risk)$/);
  const groupLink = pathname === "/api/groups/link";
  const resources = pathname.match(/^\/api\/groups\/(-?\d+)\/resources$/);
  const topics = pathname.match(/^\/api\/groups\/(-?\d+)\/topics$/);
  const topicSettings = pathname.match(/^\/api\/groups\/(-?\d+)\/topics\/(-?\d+)\/settings$/);
  const filterDelete = pathname.match(/^\/api\/groups\/(-?\d+)\/filters\/(\d+)$/);
  const userProfile = pathname.match(/^\/api\/groups\/(-?\d+)\/users\/(-?\d+)\/profile$/);
  const userList = pathname.match(/^\/api\/groups\/(-?\d+)\/users$/);
  const userAction = pathname.match(/^\/api\/groups\/(-?\d+)\/users$/);
  const authMe = pathname === "/api/auth/me";
  const admins = pathname === "/api/auth/admins";
  const adminItem = pathname.match(/^\/api\/auth\/admins\/(\d+)$/);
  const allowed = ALLOWED_GET.has(pathname) || Boolean(match) || groupLink || Boolean(resources) || Boolean(topics) || Boolean(topicSettings) || Boolean(filterDelete) || Boolean(userProfile) || Boolean(userList) || Boolean(userAction) || authMe || admins || Boolean(adminItem);
  if (!allowed) return json(res, 404, { error: "not_found" });

  if (!["GET", "PATCH", "POST", "DELETE"].includes(req.method)) {
    return json(res, 405, { error: "method_not_allowed" });
  }

  if (req.method === "PATCH" && !(match && pathname.endsWith("/settings")) && !topicSettings && !adminItem) {
    return json(res, 405, { error: "method_not_allowed" });
  }
  if (req.method === "POST" && !((match && pathname.endsWith("/filters")) || groupLink || userAction || admins)) {
    return json(res, 405, { error: "method_not_allowed" });
  }
  if (req.method === "DELETE" && !filterDelete && !adminItem) {
    return json(res, 405, { error: "method_not_allowed" });
  }

  const url = new URL(target + pathname);
  for (const [key, value] of parsedPath.searchParams.entries()) {
    url.searchParams.set(key, value);
  }
  for (const [key, value] of Object.entries(req.query)) {
    if (key !== "path" && typeof value === "string") {
      url.searchParams.set(key, value);
    }
  }

  const proxySecret = secret("GHOSTEA_PROXY_SIGNING_SECRET");
  if (!proxySecret) {
    return json(res, 500, { error: "server_not_configured" });
  }

  const requestId = crypto.randomUUID();
  const adminContext = [session.admin_id, session.role, session.username, requestId].join("\n");
  const headers = {
    Authorization: `Bearer ${secret("GHOSTEA_API_KEY")}`,
    Accept: "application/json",
    "X-Ghostea-Admin-Id": session.admin_id,
    "X-Ghostea-Role": session.role,
    "X-Ghostea-Username": session.username,
    "X-Ghostea-Admin-Signature": proxySign(adminContext),
    "X-Ghostea-Request-Id": requestId,
  };

  let body;
  if (req.method === "PATCH" || req.method === "POST") {
    const parsed = await parseBody(req).catch(() => null);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return json(res, 400, { error: "object_required" });
    }
    body = JSON.stringify(parsed);
    headers["Content-Type"] = "application/json";
  }

  const isRead = req.method === "GET";

  async function callUpstream() {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 20000);
    try {
      return await fetch(url, {
        method: req.method,
        headers,
        body,
        redirect: "error",
        signal: controller.signal,
      });
    } finally {
      clearTimeout(timer);
    }
  }

  try {
    let upstream;
    try {
      upstream = await callUpstream();
    } catch (error) {
      // Only GETs are safe to retry. Never replay dashboard mutations.
      if (!isRead) throw error;
      upstream = await callUpstream();
    }
    if (isRead && [502, 503, 504].includes(upstream.status)) {
      upstream = await callUpstream();
    }

    const text = await upstream.text();
    let payload;
    try { payload = JSON.parse(text); }
    catch { payload = { error: "upstream_invalid_response" }; }

    return json(res, upstream.status, payload, {
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
      "X-Ghostea-Request-Id": requestId,
    });
  } catch {
    return json(res, 502, { error: "ghostea_unreachable" });
  }
}
