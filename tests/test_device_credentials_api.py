"""Credentials in the device API (R1.1, R1.4, NFR-6).

Checkpoints A (never returned) and C (env fallback).
"""

import re

import pytest
from conftest import sign_in
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.configuration import NetmikoConnector
from app.credentials import StoredOrEnvironmentCredentials
from app.main import app
from app.models import Device, DeviceCredential

PASSWORD = "S3cr3t-Pass-XYZ"
SECRET = "En4ble-Secret-QRS"
DEVICE = {"name": "ios-lab-1", "management_ip": "192.0.2.10"}


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setenv("NETMGR_SECRET_KEY", Fernet.generate_key().decode())


def _admin(api):
    client, factory = api
    sign_in(client, factory, "ada", "admin")
    return client, factory


def _create(client, **extra):
    return client.post("/api/v1/devices", json={**DEVICE, **extra})


def test_r1_1_device_created_with_credentials(api, key):
    client, factory = _admin(api)
    response = _create(client, username="lab", password=PASSWORD, secret=SECRET)
    assert response.status_code == 201
    body = response.json()
    assert body["has_credentials"] is True
    assert not {"username", "password", "secret"} & set(body)  # write-only fields
    with factory() as db:
        row = db.scalar(select(DeviceCredential))
        assert row.username == "lab" and PASSWORD not in row.password_ciphertext


def test_r1_1_device_without_credentials(api, key):
    client, _ = _admin(api)
    assert _create(client).json()["has_credentials"] is False


def test_r1_1_partial_credentials_are_rejected(api, key):
    client, factory = _admin(api)
    response = _create(client, username="lab")
    assert response.status_code == 422 and "password" in response.json()["detail"].lower()
    with factory() as db:
        assert db.scalar(select(Device)) is None  # nothing half-saved


def test_r1_4_missing_key_is_503_and_saves_nothing(api, monkeypatch):
    monkeypatch.delenv("NETMGR_SECRET_KEY", raising=False)
    client, factory = _admin(api)
    response = _create(client, username="lab", password=PASSWORD)
    assert response.status_code == 503 and "NETMGR_SECRET_KEY" in response.json()["detail"]
    with factory() as db:
        assert db.scalar(select(Device)) is None


def test_r1_1_patch_sets_and_keeps_credentials(api, key):
    client, factory = _admin(api)
    device_id = _create(client).json()["id"]
    assert (
        client.patch(
            f"/api/v1/devices/{device_id}", json={"username": "lab", "password": PASSWORD}
        ).json()["has_credentials"]
        is True
    )
    kept = client.patch(f"/api/v1/devices/{device_id}", json={"ssh_port": 2222}).json()
    assert kept["has_credentials"] is True and kept["ssh_port"] == 2222
    assert (
        client.patch(f"/api/v1/devices/{device_id}", json={"password": "Only-Pass-1"}).json()[
            "has_credentials"
        ]
        is True
    )  # existing username is reused
    with factory() as db:
        assert db.scalar(select(DeviceCredential)).username == "lab"


def test_r1_4_credentials_never_appear_in_any_device_response(api, key):
    """Checkpoint A: walk every device-related response for plaintext and ciphertext."""
    client, factory = _admin(api)
    texts = []
    created = _create(client, username="lab", password=PASSWORD, secret=SECRET)
    texts.append(created.text)
    device_id = created.json()["id"]
    texts.append(
        client.patch(
            f"/api/v1/devices/{device_id}", json={"password": PASSWORD, "username": "lab"}
        ).text
    )
    texts.append(_create(client, username="lab", password=PASSWORD).text)  # 409 duplicate
    texts.append(
        client.patch("/api/v1/devices/999", json={"password": PASSWORD, "username": "x"}).text
    )  # 404
    texts.append(client.get("/api/v1/audit").text)
    for path, item in app.openapi()["paths"].items():
        if path.startswith("/api/v1/devices") and "get" in item:
            url = re.sub(r"\{device_id\}", str(device_id), path)
            url = re.sub(r"\{[^}]+\}", "1", url)
            texts.append(client.get(url).text)
    with factory() as db:
        row = db.scalar(select(DeviceCredential))
        ciphertexts = [row.password_ciphertext, row.secret_ciphertext]
    leaked = [t for t in texts for secret in (PASSWORD, SECRET, *ciphertexts) if secret in t]
    assert leaked == []
    assert len(texts) >= 8  # the walk really covered the device routes


def test_r1_1_stored_credentials_win_and_env_is_the_fallback(api, key, monkeypatch):
    """Checkpoint C: devices without stored credentials keep using the env JSON fallback."""
    client, factory = _admin(api)
    monkeypatch.setenv(
        "NETMGR_DEVICE_CREDENTIALS_JSON",
        '{"ios-lab-1": {"username": "envuser", "password": "Env-Pass-1"},'
        ' "ios-lab-2": {"username": "envuser", "password": "Env-Pass-2"}}',
    )
    _create(client, username="lab", password=PASSWORD)
    client.post("/api/v1/devices", json={"name": "ios-lab-2", "management_ip": "192.0.2.11"})
    source = StoredOrEnvironmentCredentials()
    with factory() as db:
        stored = source.get(db.scalar(select(Device).where(Device.name == "ios-lab-1")))
        fallback = source.get(db.scalar(select(Device).where(Device.name == "ios-lab-2")))
    assert (stored["username"], stored["password"], stored["host"]) == (
        "lab",
        PASSWORD,
        "192.0.2.10",
    )
    assert (fallback["username"], fallback["password"]) == ("envuser", "Env-Pass-2")


def test_r1_1_app_connector_uses_stored_credentials():
    with TestClient(app):
        connector = app.state.device_connector
        assert isinstance(connector, NetmikoConnector)
        assert isinstance(connector.credentials, StoredOrEnvironmentCredentials)
