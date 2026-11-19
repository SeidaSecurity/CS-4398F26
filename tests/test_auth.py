"""Unit tests for app/auth.py: password policy, hashing, users, sessions (SRS 4.7)."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import auth
from app.database import Base
from app.models import User, UserSession


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        yield session
    engine.dispose()


# --- R7.3 / NFR-5: password policy (NIST SP 800-63B) ------------------------------------------


@pytest.mark.parametrize(
    ("password", "ok"),
    [
        ("Abc!2345", True),  # 8 characters: lower boundary
        ("Abc!234", False),  # 7 characters: just below
        ("x" * 63 + "Q", True),  # 64 characters: upper boundary
        ("x" * 64 + "Q", False),  # 65 characters: just above
        ("password", False),  # common password
        ("PASSWORD1", False),  # common password, checked case-insensitively
        ("12345678", False),  # common password
        ("correct horse battery staple", True),  # long passphrase with spaces is allowed
    ],
)
def test_r7_3_password_policy_boundaries(password, ok):
    if ok:
        auth.validate_password(password, username="someone")
    else:
        with pytest.raises(auth.PasswordPolicyError):
            auth.validate_password(password, username="someone")


def test_r7_3_password_may_not_equal_username():
    with pytest.raises(auth.PasswordPolicyError, match="username"):
        auth.validate_password("LabAdmin2026", username="labadmin2026")


def test_r7_3_policy_errors_say_what_to_do():
    with pytest.raises(auth.PasswordPolicyError) as caught:
        auth.validate_password("short", username="u")
    assert "8" in str(caught.value)


def test_r7_3_hash_is_salted_and_not_the_password():
    first = auth.hash_password("Correct-Horse-9")
    second = auth.hash_password("Correct-Horse-9")
    assert "Correct-Horse-9" not in first
    assert first.startswith("$argon2")
    assert first != second  # random salt per hash
    assert auth.verify_password(first, "Correct-Horse-9")
    assert not auth.verify_password(first, "correct-horse-9")


def test_r7_3_verify_rejects_garbage_hash_without_raising():
    assert not auth.verify_password("not-a-hash", "anything")


def test_r7_3_create_user_stores_only_a_hash(db):
    user = auth.create_user(db, "alice", "Correct-Horse-9", "viewer")
    assert user.password_hash != "Correct-Horse-9"
    assert user.role == "viewer"
    assert user.disabled is False


@pytest.mark.parametrize("username", ["", "a" * 65, "has space", "semi;colon"])
def test_r7_3_create_user_rejects_bad_usernames(db, username):
    with pytest.raises(auth.UserValidationError):
        auth.create_user(db, username, "Correct-Horse-9", "viewer")


def test_r7_3_create_user_rejects_duplicates_and_bad_roles(db):
    auth.create_user(db, "alice", "Correct-Horse-9", "viewer")
    with pytest.raises(auth.UserValidationError, match="exists"):
        auth.create_user(db, "Alice", "Correct-Horse-9", "viewer")  # case-insensitive
    with pytest.raises(auth.UserValidationError, match="role"):
        auth.create_user(db, "bob", "Correct-Horse-9", "superuser")


# --- R7.1: authentication and sessions ----------------------------------------------------------


def test_r7_1_authenticate_success_and_generic_failure(db):
    auth.create_user(db, "alice", "Correct-Horse-9", "admin")
    assert auth.authenticate(db, "alice", "Correct-Horse-9").username == "alice"
    assert auth.authenticate(db, "alice", "wrong-password") is None
    assert auth.authenticate(db, "nobody", "Correct-Horse-9") is None


def test_r7_1_disabled_user_cannot_authenticate(db):
    user = auth.create_user(db, "alice", "Correct-Horse-9", "admin")
    user.disabled = True
    db.flush()
    assert auth.authenticate(db, "alice", "Correct-Horse-9") is None


def test_r7_1_session_token_is_stored_only_as_a_hash(db):
    user = auth.create_user(db, "alice", "Correct-Horse-9", "admin")
    token = auth.start_session(db, user)
    stored = db.query(UserSession).one()
    assert stored.token_hash != token
    assert len(token) >= 32
    assert auth.resolve_session(db, token).id == user.id


def test_r7_1_expired_session_is_rejected(db):
    user = auth.create_user(db, "alice", "Correct-Horse-9", "admin")
    token = auth.start_session(db, user, now=datetime.now(UTC) - timedelta(hours=9))
    assert auth.resolve_session(db, token) is None  # default lifetime is 8 hours


def test_r7_1_disabling_a_user_revokes_existing_sessions(db):
    user = auth.create_user(db, "alice", "Correct-Horse-9", "admin")
    token = auth.start_session(db, user)
    user.disabled = True
    db.flush()
    assert auth.resolve_session(db, token) is None


def test_r7_1_end_session_and_unknown_tokens(db):
    user = auth.create_user(db, "alice", "Correct-Horse-9", "admin")
    token = auth.start_session(db, user)
    auth.end_session(db, token)
    assert auth.resolve_session(db, token) is None
    assert auth.resolve_session(db, "made-up-token") is None
    assert db.query(User).count() == 1


# --- R7.4: first admin from ADMIN_USERNAME / ADMIN_PASSWORD -------------------------------------


def test_r7_4_bootstrap_creates_admin_once(db):
    assert auth.bootstrap_admin(db, "labadmin", "Correct-Horse-9") == "created"
    assert auth.bootstrap_admin(db, "other", "Another-Horse-9") == "exists"
    users = db.query(User).all()
    assert [(u.username, u.role) for u in users] == [("labadmin", "admin")]


@pytest.mark.parametrize(("username", "password"), [(None, None), ("labadmin", None), ("", "")])
def test_r7_4_bootstrap_not_configured(db, username, password):
    assert auth.bootstrap_admin(db, username, password) == "not_configured"
    assert db.query(User).count() == 0


def test_r7_4_bootstrap_rejects_weak_env_password(db):
    with pytest.raises(auth.PasswordPolicyError):
        auth.bootstrap_admin(db, "labadmin", "password")
    assert db.query(User).count() == 0
