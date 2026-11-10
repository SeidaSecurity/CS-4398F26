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

    def restore(self, device, configuration):
        if device.name == "ios-lab-2":
            raise RuntimeError("simulated device rejection")
        self.configurations[device.name] = configuration


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


def test_restore_configuration_creates_a_new_version_and_audit_event(client):
    test_client, testing_session = client
    device = test_client.post(
        "/api/v1/devices",
        json={"name": "ios-lab-1", "management_ip": "192.0.2.10"},
    ).json()
    original = "hostname first"
    pushed = test_client.post(
        "/api/v1/configurations/push",
        json={
            "device_ids": [device["id"]],
            "configuration": "description changed",
            "operator": "test-operator",
        },
    ).json()[0]
    target_version = pushed["before_version"]

    response = test_client.post(
        f"/api/v1/devices/{device['id']}/config/versions/{target_version}/restore",
        params={"operator": "test-operator"},
    )

    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "succeeded"
    assert result["before_version"] == 3
    assert result["after_version"] == 4
    restored = test_client.get(
        f"/api/v1/devices/{device['id']}/config/versions/{result['after_version']}"
    )
    assert restored.json()["configuration"] == original
    assert restored.json()["source"] == "rollback"

    with testing_session() as session:
        events = list(
            session.scalars(
                select(AuditRecord)
                .where(AuditRecord.action == "configuration.rollback")
                .order_by(AuditRecord.id)
            )
        )
        assert [(event.outcome, event.actor) for event in events] == [
            ("started", "test-operator"),
            ("succeeded", "test-operator"),
        ]


def test_restore_configuration_reports_device_failure(client):
    test_client, testing_session = client
    device = test_client.post(
        "/api/v1/devices",
        json={"name": "ios-lab-2", "management_ip": "192.0.2.11"},
    ).json()
    version = test_client.post(
        f"/api/v1/devices/{device['id']}/config/retrieve"
    ).json()["version"]

    response = test_client.post(
        f"/api/v1/devices/{device['id']}/config/versions/{version}/restore"
    )

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert "simulated device rejection" in response.json()["error"]
    with testing_session() as session:
        event = session.scalar(
            select(AuditRecord)
            .where(AuditRecord.action == "configuration.rollback")
            .order_by(AuditRecord.id.desc())
        )
        assert event.outcome == "failed"


def test_restore_configuration_returns_not_found_for_missing_version(client):
    test_client, _ = client
    device = test_client.post(
        "/api/v1/devices",
        json={"name": "ios-lab-1", "management_ip": "192.0.2.10"},
    ).json()

    response = test_client.post(
        f"/api/v1/devices/{device['id']}/config/versions/999/restore"
    )

    assert response.status_code == 404


def test_configuration_template_crud_and_render(client):
    test_client, _ = client
    created = test_client.post(
        "/api/v1/configuration-templates",
        json={
            "name": "Access port",
            "configuration": "interface {{ interface_name }}\n description {{ description }}",
        },
    )

    assert created.status_code == 201
    template = created.json()
    assert template["name"] == "Access port"
    assert [item["id"] for item in test_client.get("/api/v1/configuration-templates").json()] == [
        template["id"]
    ]

    rendered = test_client.post(
        "/api/v1/configuration-templates/render",
        json={
            "configuration": template["configuration"],
            "variables": {
                "interface_name": "GigabitEthernet0/1",
                "description": "Office uplink",
            },
        },
    )
    assert rendered.status_code == 200
    assert rendered.json()["configuration"] == (
        "interface GigabitEthernet0/1\n description Office uplink"
    )

    updated = test_client.patch(
        f"/api/v1/configuration-templates/{template['id']}",
        json={"name": "Office uplink"},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Office uplink"

    deleted = test_client.delete(f"/api/v1/configuration-templates/{template['id']}")
    assert deleted.status_code == 204
    assert test_client.get("/api/v1/configuration-templates").json() == []


def test_configuration_template_rejects_duplicate_name_and_missing_values(client):
    test_client, _ = client
    payload = {"name": "Shared", "configuration": "hostname {{ hostname }}"}
    assert test_client.post("/api/v1/configuration-templates", json=payload).status_code == 201
    assert test_client.post("/api/v1/configuration-templates", json=payload).status_code == 409

    response = test_client.post(
        "/api/v1/configuration-templates/render",
        json={"configuration": payload["configuration"], "variables": {}},
    )
    assert response.status_code == 422
    assert "hostname" in response.json()["detail"]


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
