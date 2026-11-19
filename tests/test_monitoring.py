import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_session
from app.main import app
from app.models import Device
from app.poller import ProbeResult, poll_all


@pytest.fixture
def client():
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(test_engine)
    testing_session = sessionmaker(bind=test_engine, expire_on_commit=False)

    def override_session():
        with testing_session() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as test_client:
        yield test_client, testing_session
    app.dependency_overrides.clear()
    Base.metadata.drop_all(test_engine)
    test_engine.dispose()


@pytest.fixture
def device(client):
    test_client, _ = client
    return test_client.post(
        "/api/v1/devices", json={"name": "router-1", "management_ip": "192.0.2.10"}
    ).json()


def test_device_patch_then_delete(client, device):
    test_client, testing_session = client
    path = f"/api/v1/devices/{device['id']}"
    response = test_client.patch(path, json={"name": "renamed-router"})
    assert response.status_code == 200
    assert response.json()["name"] == "renamed-router"
    assert test_client.get("/api/v1/devices").json()[0]["name"] == "renamed-router"
    assert test_client.delete(path).status_code == 204
    assert test_client.get("/api/v1/devices").json() == []
    with testing_session() as session:
        assert session.get(Device, device["id"]) is None


def test_poller_failure_and_recovery(client, device):
    test_client, testing_session = client
    for _ in range(2):
        poll_all(testing_session, lambda device: ProbeResult(reachable=False))
    status = test_client.get("/api/v1/monitoring/status").json()[0]
    assert status["state"] == "down"
    assert status["consecutive_failures"] == 2
    alerts = test_client.get("/api/v1/monitoring/alerts").json()
    assert len(alerts) == 1
    assert alerts[0]["device_id"] == device["id"]
    poll_all(testing_session, lambda device: ProbeResult(reachable=True))
    assert test_client.get("/api/v1/monitoring/status").json()[0]["state"] == "up"
    assert test_client.get("/api/v1/monitoring/alerts").json() == []


def test_monitoring_response_shapes_after_poll(client, device):
    test_client, testing_session = client
    poll_all(testing_session, lambda device: ProbeResult(reachable=True))
    for endpoint in ("status", "alerts", "topology"):
        response = test_client.get(f"/api/v1/monitoring/{endpoint}")
        assert response.status_code == 200
        assert isinstance(response.json(), list)
    status = test_client.get("/api/v1/monitoring/status").json()[0]
    assert status["device_id"] == device["id"]
    assert set(status) == {"device_id", "state", "last_poll_at", "consecutive_failures"}
    metrics = test_client.get("/api/v1/monitoring/metrics?window=1h")
    assert metrics.status_code == 200
    assert set(metrics.json()) == {
        "devices_up", "cpu_avg", "throughput_in_bps", "throughput_out_bps"
    }
    assert all(isinstance(points, list) for points in metrics.json().values())
    assert metrics.json()["devices_up"][0]["value"] == 1


def test_invalid_metrics_window(client):
    test_client, _ = client
    assert test_client.get("/api/v1/monitoring/metrics?window=5y").status_code == 422


def test_r2_1_poll_interval_defaults_to_60_seconds(monkeypatch):
    from app.main import poll_interval_seconds

    monkeypatch.delenv("POLL_INTERVAL_SECONDS", raising=False)
    assert poll_interval_seconds() == 60.0
    monkeypatch.setenv("POLL_INTERVAL_SECONDS", "15")
    assert poll_interval_seconds() == 15.0


@pytest.mark.parametrize("body", [{"name": None}, {"ssh_port": None}])
def test_r1_2_patch_rejects_explicit_null(client, device, body):
    """Boundary: omitted fields are unchanged, but null for a NOT NULL column is a 422."""
    test_client, _ = client
    response = test_client.patch(f"/api/v1/devices/{device['id']}", json=body)
    assert response.status_code == 422
    assert test_client.get("/api/v1/devices").json()[0]["name"] == device["name"]
