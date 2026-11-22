"""Server-side configuration diff (R3.4).

Checkpoint E (parity): the Python port must produce exactly what the web's original
`web/src/lib/diff.ts` produced. tests/fixtures/diff_parity.json was captured by running that
TypeScript under Node before it was removed (12 hand-picked + 40 seeded random cases).
"""

import json
from pathlib import Path

import pytest
from conftest import sign_in

from app.config_diff import MAX_DIFF_LINES, DiffTooLargeError, side_by_side
from app.configuration import save_config_version
from app.models import Device

FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "diff_parity.json").read_text())


@pytest.mark.parametrize("case", FIXTURES, ids=[f"case{i}" for i in range(len(FIXTURES))])
def test_r3_4_parity_with_original_typescript_diff(case):
    assert side_by_side(case["a"], case["b"]) == case["expected"]


def test_r3_4_fixture_set_is_meaningful():
    kinds = {row["kind"] for case in FIXTURES for row in case["expected"]["rows"]}
    assert kinds == {"same", "removed", "added", "changed"} and len(FIXTURES) >= 50


def test_r3_4_size_cap():
    big = "\n".join(f"line {n}" for n in range(MAX_DIFF_LINES + 1))
    with pytest.raises(DiffTooLargeError):
        side_by_side(big, "x")
    with pytest.raises(DiffTooLargeError):
        side_by_side("x", big)
    at_cap = "\n".join(f"line {n}" for n in range(MAX_DIFF_LINES))
    assert side_by_side(at_cap, at_cap)["added"] == 0  # identical at the cap: fast path


def _setup(api, role="viewer"):
    client, factory = api
    sign_in(client, factory, "vic", role)
    with factory() as db:
        device = Device(name="r1", management_ip="192.0.2.1")
        db.add(device)
        db.flush()
        save_config_version(db, device.id, "hostname r1\nend", "retrieve", "ada")
        save_config_version(db, device.id, "hostname r1-new\nend\n", "push", "ada")
        db.commit()
        return client, device.id


def test_r3_4_diff_endpoint(api):
    client, device_id = _setup(api)  # a viewer may read diffs (GET)
    response = client.get(f"/api/v1/devices/{device_id}/config/diff?from=1&to=2")
    assert response.status_code == 200
    body = response.json()
    assert body["from_version"]["version"] == 1 and body["to_version"]["version"] == 2
    assert "configuration" not in body["from_version"]
    expected = side_by_side("hostname r1\nend", "hostname r1-new\nend\n")
    assert {k: body[k] for k in ("rows", "added", "removed")} == expected
    assert body["rows"][0] == {
        "kind": "changed",
        "left": {"n": 1, "text": "hostname r1"},
        "right": {"n": 1, "text": "hostname r1-new"},
    }
    assert "left" not in body["rows"][-1]  # absent sides are omitted, as in the old client diff


def test_r3_4_diff_same_version(api):
    client, device_id = _setup(api)
    body = client.get(f"/api/v1/devices/{device_id}/config/diff?from=2&to=2").json()
    assert body["added"] == body["removed"] == 0


@pytest.mark.parametrize(
    ("path", "detail"),
    [
        ("/api/v1/devices/999/config/diff?from=1&to=2", "Device not found"),
        ("/api/v1/devices/{id}/config/diff?from=1&to=9", "Configuration version 9 not found"),
    ],
)
def test_r3_4_diff_not_found(api, path, detail):
    client, device_id = _setup(api)
    response = client.get(path.replace("{id}", str(device_id)))
    assert response.status_code == 404 and response.json()["detail"] == detail


def test_r3_4_diff_requires_both_versions(api):
    client, device_id = _setup(api)
    assert client.get(f"/api/v1/devices/{device_id}/config/diff?from=1").status_code == 422


def test_r3_4_diff_too_large_is_operator_message(api, monkeypatch):
    client, device_id = _setup(api)
    monkeypatch.setattr("app.config_diff.MAX_DIFF_LINES", 1)
    response = client.get(f"/api/v1/devices/{device_id}/config/diff?from=1&to=2")
    assert response.status_code == 422
    assert "too large" in response.json()["detail"].lower()
