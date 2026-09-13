# Phase 31 — Security Audit & Attack-Surface Hardening

- Clean HTTPS-only Vercel upstream target policy.
- Proxy identity signatures bind to method/path and a short-lived timestamp.
- Render rejects stale/replayed proxy signatures.
- Dashboard sessions remain HttpOnly/Secure/SameSite=Lax.
- Admin bootstrap usernames use the same strict username grammar as managed admins.
- Stored scrypt parameters are bounded before verification to prevent resource-exhaustion hashes.
- Deterministic security audit helper avoids secret disclosure.
- No database migration.
