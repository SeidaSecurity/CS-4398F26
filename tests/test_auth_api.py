"""API tests for login, logout and the current user (R7.1, R4.4, SRS 3.1.1)."""

from conftest import TEST_PASSWORD, add_user
from sqlalchemy import select

from app import auth
from app.models import AuditRecord, UserSession


def _login(client, username, password):
    return client.post("/api/v1/auth/login", json={"username": username, "password": password})


def _audit(factory, action):
    with factory() as db:
        return [
            (r.actor, r.outcome)
            for r in db.scalars(
                select(AuditRecord).where(AuditRecord.action == action).order_by(AuditRecord.id)
            )
        ]


def test_r7_1_login_sets_httponly_session_cookie_and_returns_user(api):
    client, factory = api
    add_user(factory, "alice", "admin")

    response = _login(client, "alice", TEST_PASSWORD)

    assert response.status_code == 200
    assert response.json()["username"] == "alice"
    assert response.json()["role"] == "admin"
    assert "password" not in response.text.lower()  # neither the password nor its hash
    cookie = response.headers["set-cookie"].lower()
    assert f"{auth.SESSION_COOKIE}=" in cookie
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "secure" not in cookie  # no HTTPS yet; COOKIE_SECURE=true turns it on


def test_r7_1_cookie_secure_flag_follows_env(api, monkeypatch):
    client, factory = api
    add_user(factory, "alice", "admin")
    monkeypatch.setenv("COOKIE_SECURE", "true")
    assert "secure" in _login(client, "alice", TEST_PASSWORD).headers["set-cookie"].lower()


def test_r7_1_failed_login_is_generic_for_wrong_password_unknown_user_and_disabled(api):
    """SRS 3.1.1: the error must not reveal whether the username exists."""
    client, factory = api
    add_user(factory, "alice", "admin")
    add_user(factory, "carol", "viewer")
    with factory() as db:
        auth.find_user(db, "carol").disabled = True
        db.commit()

    responses = [
        _login(client, "alice", "Wrong-Horse-9"),
        _login(client, "nobody", TEST_PASSWORD),
        _login(client, "carol", TEST_PASSWORD),
    ]

    assert {r.status_code for r in responses} == {401}
    assert len({r.text for r in responses}) == 1  # byte-identical bodies
    assert all("set-cookie" not in r.headers for r in responses)


def test_r4_4_logins_are_audited(api):
    client, factory = api
    add_user(factory, "alice", "admin")
    _login(client, "alice", TEST_PASSWORD)
    _login(client, "alice", "Wrong-Horse-9")
    _login(client, "mallory", "Whatever-9")
    assert _audit(factory, "auth.login") == [
        ("alice", "succeeded"),
        ("alice", "failed"),
        ("mallory", "failed"),
    ]


def test_r7_1_me_requires_a_session(api):
    client, factory = api
    add_user(factory, "alice", "viewer")
    assert client.get("/api/v1/auth/me").status_code == 401
    _login(client, "alice", TEST_PASSWORD)
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert (me.json()["username"], me.json()["role"]) == ("alice", "viewer")


def test_r7_1_logout_revokes_the_session_and_is_audited(api):
    client, factory = api
    add_user(factory, "alice", "admin")
    _login(client, "alice", TEST_PASSWORD)

    response = client.post("/api/v1/auth/logout")

    assert response.status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401
    with factory() as db:
        assert db.scalar(select(UserSession)) is None  # removed server-side, not just the cookie
    assert _audit(factory, "auth.logout") == [("alice", "succeeded")]


def test_r7_1_logout_without_a_session_is_harmless(api):
    client, _ = api
    assert client.post("/api/v1/auth/logout").status_code == 204
