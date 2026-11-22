"""Route-coverage tests for the access policy (R7.1, R7.2), checkpoint B of the auth plan.

Every operation is discovered from the OpenAPI schema, NOT from app.routes: in this FastAPI
version, routes added with include_router (e.g. all of /api/v1/monitoring) are not listed in
app.routes, so a test built on app.routes would silently skip them. A new route is covered
automatically; nobody has to remember to add it here.
"""

import re

from conftest import sign_in
from sqlalchemy import select

from app.main import app
from app.models import AuditRecord, Device

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
PUBLIC = {("POST", "/api/v1/auth/login"), ("POST", "/api/v1/auth/logout")}
ADMIN_ONLY_READ_PREFIXES = ("/api/v1/users",)
MIN_EXPECTED_OPERATIONS = 48  # 37 + DHCP (9), test-connection, config diff


def _operations():
    ops = []
    for path, item in app.openapi()["paths"].items():
        for method in item:
            ops.append((method.upper(), path, re.sub(r"\{[^}]+\}", "1", path)))
    return ops


def _call(client, method, url):
    return client.request(method, url, json={}) if method not in SAFE_METHODS else client.get(url)


def test_r7_route_walk_is_complete():
    ops = _operations()
    paths = {path for _, path, _ in ops}
    assert len(ops) >= MIN_EXPECTED_OPERATIONS
    assert any(p.startswith("/api/v1/monitoring") for p in paths)  # included-router routes found


def test_r7_1_every_api_route_rejects_anonymous_callers(api):
    client, _ = api
    unprotected = []
    for method, path, url in _operations():
        if not path.startswith("/api/v1/") or (method, path) in PUBLIC:
            continue
        if _call(client, method, url).status_code != 401:
            unprotected.append(f"{method} {path}")
    assert unprotected == []


def test_r7_1_public_routes_stay_reachable(api):
    client, _ = api
    assert client.get("/health").status_code == 200
    assert client.post("/api/v1/auth/login", json={}).status_code == 422  # validation, not 401


def test_r7_2_every_write_route_rejects_a_viewer(api):
    client, factory = api
    sign_in(client, factory, "vera", "viewer")
    allowed_writes, blocked_reads = [], []
    for method, path, url in _operations():
        if not path.startswith("/api/v1/") or (method, path) in PUBLIC:
            continue
        status = _call(client, method, url).status_code
        admin_only = method not in SAFE_METHODS or path.startswith(ADMIN_ONLY_READ_PREFIXES)
        if admin_only and status != 403:
            allowed_writes.append(f"{method} {path} -> {status}")
        if not admin_only and status in (401, 403):
            blocked_reads.append(f"{method} {path} -> {status}")
    assert allowed_writes == []
    assert blocked_reads == []  # viewers can still observe (SRS 2.3)


def test_r7_2_viewer_refusal_changes_nothing_and_is_audited(api):
    client, factory = api
    sign_in(client, factory, "vera", "viewer")

    response = client.post("/api/v1/devices", json={"name": "r9", "management_ip": "192.0.2.9"})

    assert response.status_code == 403
    assert "viewer" in response.json()["detail"].lower()
    with factory() as db:
        assert db.scalar(select(Device)) is None
        refusal = db.scalar(select(AuditRecord).where(AuditRecord.action == "access.denied"))
        assert (refusal.actor, refusal.outcome, refusal.detail) == (
            "vera",
            "refused",
            "POST /api/v1/devices",
        )


def test_r7_2_admin_passes_the_policy(api):
    client, factory = api
    sign_in(client, factory, "ada", "admin")
    response = client.post("/api/v1/devices", json={"name": "r9", "management_ip": "192.0.2.9"})
    assert response.status_code == 201
