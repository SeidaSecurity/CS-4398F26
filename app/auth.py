"""Authentication and access control (SRS 4.7): passwords, users, sessions, access policy.

Route handlers stay thin; everything security-relevant lives here so it can be unit-tested.
Decisions: docs/decisions/0005-authentication-and-sessions.md.
"""

import hashlib
import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import Literal

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.common_passwords import COMMON_PASSWORDS
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
