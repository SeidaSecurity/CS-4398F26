"""Account management API (R7.4, R4.4): admin-only create, change role, disable, reset password."""

from conftest import sign_in
from sqlalchemy import select

from app.models import AuditRecord


def _admin(api):
    client, factory = api
    sign_in(client, factory, "ada", "admin")
    return client, factory


def _create(client, username, role="viewer", password="Another-Horse-9"):
    return client.post(
        "/api/v1/users", json={"username": username, "password": password, "role": role}
    )


def _audit(factory, action):
    with factory() as db:
        return [
            (r.actor, r.outcome, r.detail)
            for r in db.scalars(
                select(AuditRecord).where(AuditRecord.action == action).order_by(AuditRecord.id)
            )
        ]


def test_r7_4_admin_creates_a_user_who_can_then_log_in(api):
    client, factory = _admin(api)

    response = _create(client, "vera")

    assert response.status_code == 201
    body = response.json()
    assert (body["username"], body["role"], body["disabled"]) == ("vera", "viewer", False)
    assert "password" not in response.text.lower()  # neither password nor hash returned
    assert _audit(factory, "user.create") == [("ada", "succeeded", "Created viewer 'vera'")]
    login = client.post(
        "/api/v1/auth/login", json={"username": "vera", "password": "Another-Horse-9"}
    )
    assert login.status_code == 200


def test_r7_4_create_rejects_weak_password_duplicates_and_bad_roles(api):
    client, _ = _admin(api)
    weak = _create(client, "vera", password="password")
    assert weak.status_code == 422
    assert "common" in weak.json()["detail"]
    assert _create(client, "vera").status_code == 201
    assert _create(client, "VERA").status_code == 409  # usernames are case-insensitive
    assert _create(client, "otto", role="superuser").status_code == 422


def test_r7_4_list_users_never_exposes_hashes(api):
    client, _ = _admin(api)
    _create(client, "vera")
    response = client.get("/api/v1/users")
    assert response.status_code == 200
    assert [u["username"] for u in response.json()] == ["ada", "vera"]
    assert "argon2" not in response.text and "password" not in response.text.lower()


def test_r7_4_change_role_is_audited(api):
    client, factory = _admin(api)
    vera = _create(client, "vera").json()

    response = client.patch(f"/api/v1/users/{vera['id']}", json={"role": "admin"})

    assert response.status_code == 200
    assert response.json()["role"] == "admin"
    assert _audit(factory, "user.update") == [("ada", "succeeded", "User 'vera': role -> admin")]


def test_r7_4_disabling_a_user_ends_their_access_immediately(api):
    client, factory = _admin(api)
    vera = _create(client, "vera").json()
    # vera logs in on her own client
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as vera_client:
        vera_client.post(
            "/api/v1/auth/login", json={"username": "vera", "password": "Another-Horse-9"}
        )
        assert vera_client.get("/api/v1/auth/me").status_code == 200

        client.patch(f"/api/v1/users/{vera['id']}", json={"disabled": True})

        assert vera_client.get("/api/v1/auth/me").status_code == 401  # existing session revoked
        relogin = vera_client.post(
            "/api/v1/auth/login", json={"username": "vera", "password": "Another-Horse-9"}
        )
        assert relogin.status_code == 401


def test_r7_4_last_active_admin_cannot_be_demoted_or_disabled(api):
    client, _ = _admin(api)
    ada_id = client.get("/api/v1/auth/me").json()["id"]

    demote = client.patch(f"/api/v1/users/{ada_id}", json={"role": "viewer"})
    disable = client.patch(f"/api/v1/users/{ada_id}", json={"disabled": True})

    assert demote.status_code == 409
    assert disable.status_code == 409
    assert "last" in demote.json()["detail"].lower()


def test_r7_4_an_admin_can_be_demoted_when_another_admin_remains(api):
    client, _ = _admin(api)
    otto = _create(client, "otto", role="admin").json()
    assert client.patch(f"/api/v1/users/{otto['id']}", json={"role": "viewer"}).status_code == 200


def test_r7_4_password_reset_enforces_policy_and_replaces_the_old_password(api):
    client, _ = _admin(api)
    vera = _create(client, "vera").json()
    url = f"/api/v1/users/{vera['id']}"

    assert client.patch(url, json={"password": "short"}).status_code == 422
    assert client.patch(url, json={"password": "Brand-New-Horse-7"}).status_code == 200

    def login(password):
        return client.post("/api/v1/auth/login", json={"username": "vera", "password": password})

    assert login("Another-Horse-9").status_code == 401
    assert login("Brand-New-Horse-7").status_code == 200


def test_r7_4_unknown_user_and_null_fields(api):
    client, _ = _admin(api)
    assert client.patch("/api/v1/users/999", json={"role": "viewer"}).status_code == 404
    assert client.patch("/api/v1/users/1", json={"role": None}).status_code == 422


def test_r7_2_viewer_cannot_manage_or_even_list_accounts(api):
    client, factory = api
    sign_in(client, factory, "vera", "viewer")
    assert client.get("/api/v1/users").status_code == 403
    assert _create(client, "eve", role="admin").status_code == 403
