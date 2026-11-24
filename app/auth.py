"""Authentication and access control (SRS 4.7): passwords, users, sessions, access policy.

Route handlers stay thin; everything security-relevant lives here so it can be unit-tested.
Decisions: docs/decisions/0005-authentication-and-sessions.md.
"""

import hashlib
import os
import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import Literal

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, HTTPException, Request
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.common_passwords import COMMON_PASSWORDS
from app.database import get_session
from app.models import User, UserSession

Role = Literal["admin", "viewer"]
ROLES: tuple[str, ...] = ("admin", "viewer")
SESSION_COOKIE = "netmgr_session"
DEFAULT_SESSION_HOURS = 8.0
MIN_PASSWORD, MAX_PASSWORD = 8, 64
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

_hasher = PasswordHasher()
_dummy_hash: str | None = None


class PasswordPolicyError(ValueError):
    """The password breaks the NIST SP 800-63B rules; the message says how to fix it."""


class UserValidationError(ValueError):
    """Bad username, duplicate user, or unknown role; the message says how to fix it."""


# --- Passwords (R7.3, NFR-5) ---------------------------------------------------------------------


def validate_password(password: str, username: str) -> None:
    if not MIN_PASSWORD <= len(password) <= MAX_PASSWORD:
        raise PasswordPolicyError(
            f"Password must be {MIN_PASSWORD}-{MAX_PASSWORD} characters long; "
            "a passphrase of several words works well."
        )
    if password.lower() in COMMON_PASSWORDS:
        raise PasswordPolicyError("That password is too common. Choose a less predictable one.")
    if password.lower() == username.lower():
        raise PasswordPolicyError("Password must not be the same as the username.")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def _equalize_timing(password: str) -> None:
    """Spend the same hashing time for unknown users, so timing doesn't reveal usernames."""
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = _hasher.hash("timing-equalizer-not-a-real-password")
    verify_password(_dummy_hash, password)


# --- Users (R7.4) --------------------------------------------------------------------------------


def find_user(db: Session, username: str) -> User | None:
    return db.scalar(select(User).where(func.lower(User.username) == username.lower()))


def create_user(db: Session, username: str, password: str, role: str) -> User:
    if not USERNAME_PATTERN.fullmatch(username):
        raise UserValidationError(
            "Username must be 1-64 characters: letters, digits, '.', '_' or '-'."
        )
    if role not in ROLES:
        raise UserValidationError(f"Unknown role '{role}'. Use 'admin' or 'viewer'.")
    if find_user(db, username) is not None:
        raise UserValidationError(f"A user named '{username}' already exists.")
    validate_password(password, username)
    user = User(username=username, password_hash=hash_password(password), role=role)
    db.add(user)
    db.flush()
    return user


def bootstrap_admin(
    db: Session, username: str | None, password: str | None
) -> Literal["created", "exists", "not_configured"]:
    """Create the first admin from ADMIN_USERNAME / ADMIN_PASSWORD, only if no users exist.

    Raises PasswordPolicyError / UserValidationError if the configured values are unacceptable.
    """
    if db.scalar(select(func.count()).select_from(User)):
        return "exists"
    if not username or not password:
        return "not_configured"
    create_user(db, username, password, "admin")
    return "created"


def active_admin_count(db: Session) -> int:
    return db.scalar(
        select(func.count()).select_from(User).where(User.role == "admin", User.disabled.is_(False))
    ) or 0


# --- Sessions (R7.1) -----------------------------------------------------------------------------


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _as_utc(value: datetime) -> datetime:
    # SQLite returns naive datetimes even for timezone-aware columns.
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def authenticate(db: Session, username: str, password: str) -> User | None:
    """Return the user for valid credentials; None for every kind of failure (generic, R7.1)."""
    user = find_user(db, username)
    if user is None or user.disabled:
        _equalize_timing(password)
        return None
    return user if verify_password(user.password_hash, password) else None


def start_session(
    db: Session, user: User, hours: float = DEFAULT_SESSION_HOURS, now: datetime | None = None
) -> str:
    """Create a session and return the raw token for the cookie (only its hash is stored)."""
    now = now or datetime.now(UTC)
    token = secrets.token_urlsafe(32)
    db.add(
        UserSession(
            token_hash=_token_hash(token),
            user_id=user.id,
            created_at=now,
            expires_at=now + timedelta(hours=hours),
        )
    )
    db.flush()
    return token


def resolve_session(db: Session, token: str, now: datetime | None = None) -> User | None:
    """The logged-in user for a cookie token, or None if unknown, expired, or disabled."""
    record = db.scalar(select(UserSession).where(UserSession.token_hash == _token_hash(token)))
    if record is None or _as_utc(record.expires_at) <= (now or datetime.now(UTC)):
        return None
    user = db.get(User, record.user_id)
    return None if user is None or user.disabled else user


def end_session(db: Session, token: str) -> None:
    db.execute(delete(UserSession).where(UserSession.token_hash == _token_hash(token)))
    db.flush()


# --- Settings ------------------------------------------------------------------------------------


def session_hours() -> float:
    return float(os.getenv("SESSION_HOURS", str(DEFAULT_SESSION_HOURS)))


def cookie_secure() -> bool:
    """Secure-flag the cookie once HTTPS exists (NFR-7); off by default for the HTTP lab."""
    return os.getenv("COOKIE_SECURE", "false").lower() == "true"


# --- FastAPI dependencies ------------------------------------------------------------------------

NOT_LOGGED_IN = "You are not logged in. Log in and try again."


def current_user(request: Request, db: Session = Depends(get_session)) -> User:
    """The logged-in user (from the session cookie), or 401."""
    user = getattr(request.state, "user", None)
    if user is None:
        token = request.cookies.get(SESSION_COOKIE)
        user = resolve_session(db, token) if token else None
    if user is None:
        raise HTTPException(status_code=401, detail=NOT_LOGGED_IN)
    request.state.user = user
    return user


# --- Central access policy (R7.1, R7.2); design point 1 of ADR-0005 -------------------------------

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
PUBLIC_OPERATIONS = frozenset({("POST", "/api/v1/auth/login"), ("POST", "/api/v1/auth/logout")})
ADMIN_ONLY_READ_PREFIXES = ("/api/v1/users",)
VIEWER_REFUSED = (
    "Your account is read-only (viewer), so this change was not made. "
    "Ask an administrator to make it or to change your role."
)


def enforce_access(request: Request, db: Session = Depends(get_session)) -> None:
    """Applied to every route: anonymous -> 401 on /api/v1; viewer -> 403 (audited) on writes.

    One policy for the whole API, so a new route cannot be left unprotected by accident;
    tests/test_access_policy.py walks every OpenAPI operation to prove it.
    """
    from app.configuration import record_audit_event  # local import avoids a cycle at startup

    method, path = request.method.upper(), request.url.path
    if not path.startswith("/api/v1/") or (method, path) in PUBLIC_OPERATIONS:
        return
    # CS4398_FOUR_DEVICE_LOCALHOST_TOKEN_GUARD (opt-in; never bypass other routes)
    if method == "POST" and path in ("/api/v1/demo/setup-four", "/api/v1/demo/activate-standby"):
        import hmac
        secret = os.getenv("CS4398_DEMO_ACTIVATION_TOKEN", "")
        token = request.headers.get("X-Demo-Token", "")
        if (secret and token and request.client and
                request.client.host in ("127.0.0.1", "::1") and
                hmac.compare_digest(secret, token)):
            return
    user = current_user(request, db)  # raises 401 when not logged in
    needs_admin = method not in SAFE_METHODS or path.startswith(ADMIN_ONLY_READ_PREFIXES)
    if needs_admin and user.role != "admin":
        record_audit_event(db, user.username, "access.denied", "refused", detail=f"{method} {path}")
        db.commit()
        raise HTTPException(status_code=403, detail=VIEWER_REFUSED)


# --- Account management (R7.4) -------------------------------------------------------------------


class LastAdminError(ValueError):
    """The change would leave no active administrator."""


def update_user(
    db: Session,
    user: User,
    role: str | None = None,
    disabled: bool | None = None,
    password: str | None = None,
) -> list[str]:
    """Apply changes and return a description of each (for the audit log; never the password)."""
    if role is not None and role not in ROLES:
        raise UserValidationError(f"Unknown role '{role}'. Use 'admin' or 'viewer'.")
    loses_admin = user.role == "admin" and not user.disabled and (
        (role is not None and role != "admin") or disabled is True
    )
    if loses_admin and active_admin_count(db) <= 1:
        raise LastAdminError(
            f"'{user.username}' is the last active administrator. "
            "Make another user an admin first."
        )
    changes = []
    if role is not None and role != user.role:
        user.role = role
        changes.append(f"role -> {role}")
    if disabled is not None and disabled != user.disabled:
        user.disabled = disabled
        changes.append("disabled" if disabled else "enabled")
    if password is not None:
        validate_password(password, user.username)
        user.password_hash = hash_password(password)
        changes.append("password reset")
    db.flush()
    return changes
