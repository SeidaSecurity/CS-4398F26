from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_session
from app.main import app
from app.models import AuditRecord, ConfigVersion, LogRecord


class FakeConnector:
    def __init__(self):
        self.configurations = {
            "ios-lab-1": "hostname first",
            "ios-lab-2": "hostname second",
        }

    def retrieve(self, device):
        return self.configurations[device.name]

    def push(self, device, configuration):
        if device.name == "ios-lab-2":
            raise RuntimeError("simulated device rejection")
        self.configurations[device.name] = f"{self.configurations[device.name]}\n{configuration}"


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
        app.state.device_connector = FakeConnector()
        yield test_client, testing_session
    app.dependency_overrides.clear()
    Base.metadata.drop_all(test_engine)
    test_engine.dispose()


def test_device_create_and_duplicate_conflict(client):
    test_client, _ = client
    payload = {"name": "ios-lab-1", "management_ip": "192.0.2.10"}

    response = test_client.post("/api/v1/devices", json=payload)
    assert response.status_code == 201
    assert response.json()["platform"] == "cisco_ios"

    duplicate = test_client.post("/api/v1/devices", json=payload)
    assert duplicate.status_code == 409
    assert test_client.get("/api/v1/devices").json()[0]["name"] == "ios-lab-1"


def test_push_saves_versions_and_continues_after_device_failure(client):
    test_client, testing_session = client
    first = test_client.post(
        "/api/v1/devices",
        json={"name": "ios-lab-1", "management_ip": "192.0.2.10"},
    ).json()
    second = test_client.post(
        "/api/v1/devices",
        json={"name": "ios-lab-2", "management_ip": "192.0.2.11"},
    ).json()

    response = test_client.post(
        "/api/v1/configurations/push",
        json={
            "device_ids": [first["id"], second["id"], 999],
            "configuration": "description managed",
            "operator": "test-operator",
        },
    )

    results = response.json()
    assert [result["status"] for result in results] == ["succeeded", "failed", "failed"]
    assert results[0]["before_version"] == 1
    assert results[0]["after_version"] == 2
    assert "simulated device rejection" in results[1]["error"]
    version = test_client.get(f"/api/v1/devices/{first['id']}/config/versions/2")
    assert version.status_code == 200
    assert "description managed" in version.json()["configuration"]

    with testing_session() as session:
        versions = list(
            session.scalars(select(ConfigVersion).where(ConfigVersion.device_id == second["id"]))
        )
        assert [(version.version, version.source) for version in versions] == [(1, "pre_push")]
        events = list(session.scalars(select(AuditRecord).order_by(AuditRecord.id)))
        events = [event for event in events if not event.action.startswith("device.")]
        assert [event.outcome for event in events] == ["started", "succeeded", "started", "failed"]
    assert len(
        [
            event
            for event in test_client.get("/api/v1/audit").json()
            if not event["action"].startswith("device.")
        ]
    ) == 4


def test_log_search_filters_records(client):
    test_client, testing_session = client
    with testing_session() as session:
        session.add(
            LogRecord(
                timestamp=datetime(2025, 2, 1, 12, tzinfo=UTC),
                source="router1",
                facility=1,
                severity=5,
                body="link changed",
                raw_message="<13>1 ... link changed",
                parsed=True,
            )
        )
        session.add(
            LogRecord(
                timestamp=datetime(2025, 2, 1, 12, 1, tzinfo=UTC),
                source="switch1",
                facility=4,
                severity=2,
                body="interface down",
                raw_message="<34>1 ... interface down",
                parsed=True,
            )
        )
        session.commit()

    response = test_client.get("/api/v1/logs", params={"query": "LINK", "severity": 5})

    assert response.status_code == 200
    assert [item["source"] for item in response.json()] == ["router1"]
