# ADR-0005: Authentication, sessions, and a central access policy

- **Status:** Accepted (2026-11-19). Changes the frozen REST auth contract (SRS 9.4).
- **Requirements:** R7.1–R7.4, R3.3, R4.4, NFR-5; SRS 3.1.1

## Context
The API was open: anyone on the lab network could push configuration, and the audit log recorded
a caller-typed `operator` instead of a verified identity. SRS 4.7 requires login for every
screen and endpoint, two roles (admin can change state, viewer can only observe), salted
password hashes, and an audit trail of logins and refusals.

## Decision
1. **Sessions:** an HTTP-only, `SameSite=Lax` cookie (`netmgr_session`) holds a random 256-bit
   token. The `user_sessions` table stores only its SHA-256 hash and an expiry (default 8 h,
   `SESSION_HOURS`). Because sessions are checked server-side, disabling a user revokes their
   access immediately. `Secure` is off until HTTPS exists (`COOKIE_SECURE=true`, NFR-7).
2. **Passwords:** argon2id (`argon2-cffi`) with a per-hash salt. Policy (NIST SP 800-63B):
   8–64 characters, not on a bundled common-password list, not equal to the username.
3. **First admin:** created at startup from `ADMIN_USERNAME` / `ADMIN_PASSWORD`, only when no
   users exist. Startup doesn't touch the database when these are unset.
4. **One central access policy** (`auth.enforce_access`, an app-wide dependency) instead of a
   check on each route:
   - anonymous request to `/api/v1/*` → **401** (except `POST /auth/login` and `/auth/logout`);
   - viewer making any non-GET request, or any request under `/api/v1/users` → **403**, audited
     as `access.denied` / `refused`.
   A new route is protected automatically. `tests/test_access_policy.py` walks every OpenAPI
   operation to prove it. The tests use the OpenAPI schema because routes added via
   `include_router` are not visible in `app.routes` in this FastAPI version.
5. **Endpoints:** `POST /api/v1/auth/login`, `POST /api/v1/auth/logout` (idempotent),
   `GET /api/v1/auth/me`. Every login failure returns the same 401 body
   ("Invalid username or password."), and unknown users still cost one hash verification, so
   neither the message nor the timing reveals whether a username exists.
6. **Template preview counts as a write:** `POST /configuration-templates/render` changes nothing
   but is admin-only, so the rule stays simple: every non-GET request needs an admin.

## Consequences
- Every client must log in. The web UI needs a Login screen, and `scripts/check-lab.ps1` must
  authenticate (auth increments 7–8).
- Only new tables (`users`, `user_sessions`) were added, so existing lab databases keep working
  without a migration.
- Tests sign in by inserting a session directly (`tests/conftest.py::sign_in`), so they add no
  login audit records. Existing tests needed only a fixture change.
- Idle-timeout expiry (R7.5) and HTTPS (NFR-7) remain open.
