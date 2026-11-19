from datetime import UTC, datetime

import pytest
from conftest import sign_in
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.configuration import DeviceRejectedError, DeviceUnreachableError
from app.database import Base, get_session
from app.main import app
from app.models import AuditRecord, ConfigVersion, LogRecord


class FakeConnector:
    """Simulated devices. ios-lab-1 works; ios-lab-2 rejects changes. Tests may add failures
    per (device name, operation) in ``failures`` to inject faults at a chosen phase."""

    def __init__(self):
        self.configurations = {
            "ios-lab-1": "hostname first",
            "ios-lab-2": "hostname second",
        }
        self.failures: dict[tuple[str, str], list[Exception]] = {}

    def _maybe_fail(self, device, operation):
        queued = self.failures.get((device.name, operation))
        if queued:
            raise queued.pop(0)

    def retrieve(self, device):
        self._maybe_fail(device, "retrieve")
        return self.configurations[device.name]

    def push(self, device, configuration):
        self._maybe_fail(device, "push")
        if device.name == "ios-lab-2":
            raise DeviceRejectedError("simulated device rejection")
        self.configurations[device.name] = f"{self.configurations[device.name]}\n{configuration}"

    def restore(self, device, configuration):
        if device.name == "ios-lab-2":
            raise DeviceRejectedError("simulated device rejection")
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
        sign_in(test_client, testing_session, "test-admin", "admin")  # R7.1: API needs login
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
    assert [result["status"] for result in results] == ["succeeded", "rejected", "not_found"]
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
    assert response.json()["status"] == "rejected"
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


def test_r4_4_template_changes_are_audited(client):
    test_client, _ = client
    template = test_client.post(
        "/api/v1/configuration-templates",
        json={"name": "Banner", "configuration": "banner motd {{ text }}"},
        params={"operator": "alice"},
    ).json()
    test_client.patch(
        f"/api/v1/configuration-templates/{template['id']}",
        json={"configuration": "banner motd #{{ text }}#"},
        params={"operator": "alice"},
    )
    test_client.delete(
        f"/api/v1/configuration-templates/{template['id']}", params={"operator": "alice"}
    )

    events = [
        (event["action"], event["actor"], event["outcome"])
        for event in reversed(test_client.get("/api/v1/audit").json())
    ]
    assert events == [
        ("template.create", "alice", "succeeded"),
        ("template.update", "alice", "succeeded"),
        ("template.delete", "alice", "succeeded"),
    ]


def test_r4_4_duplicate_template_name_is_not_audited(client):
    """Error guessing: a rejected create must not leave a 'succeeded' audit row behind."""
    test_client, _ = client
    payload = {"name": "Shared", "configuration": "hostname x"}
    test_client.post("/api/v1/configuration-templates", json=payload)
    assert test_client.post("/api/v1/configuration-templates", json=payload).status_code == 409
    actions = [event["action"] for event in test_client.get("/api/v1/audit").json()]
    assert actions == ["template.create"]


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("100%", ["cpu at 100% on core 0"]),  # literal percent sign
        ("Gi0_1", ["Gi0_1 up"]),  # literal underscore
        ("%", ["cpu at 100% on core 0"]),  # a bare wildcard must not match everything
        ("cpu", ["cpu at 100% on core 0"]),  # ordinary substring still works
    ],
)
def test_r4_3_search_treats_like_wildcards_literally(client, query, expected):
    """Equivalence classes: text containing %, containing _, wildcard only, plain text."""
    test_client, testing_session = client
    with testing_session() as session:
        for minute, body in enumerate(["cpu at 100% on core 0", "Gi0_1 up", "Gi0/1 down"]):
            session.add(
                LogRecord(
                    timestamp=datetime(2025, 2, 1, 12, minute, tzinfo=UTC),
                    source="router1",
                    facility=1,
                    severity=5,
                    body=body,
                    raw_message=body,
                    parsed=True,
                )
            )
        session.commit()

    response = test_client.get("/api/v1/logs", params={"query": query})

    assert [item["body"] for item in response.json()] == expected


def _add_device(test_client, name="ios-lab-1"):
    return test_client.post(
        "/api/v1/devices", json={"name": name, "management_ip": "192.0.2.10"}
    ).json()


def _push(test_client, device_ids):
    return test_client.post(
        "/api/v1/configurations/push",
        json={"device_ids": device_ids, "configuration": "ntp server 192.0.2.1", "operator": "op"},
    ).json()


def _change_audit(testing_session):
    with testing_session() as session:
        return [
            (event.outcome, event.detail)
            for event in session.scalars(
                select(AuditRecord)
                .where(AuditRecord.action.like("configuration.%"))
                .order_by(AuditRecord.id)
            )
        ]


def test_r3_5_unreachable_device_is_reported_as_unreachable(client):
    """SRS 4.3.4 step 5c: unreachable before any change -> no versions saved."""
    test_client, testing_session = client
    device = _add_device(test_client)
    message = "Could not reach ios-lab-1 at 192.0.2.10:22. Check that the device is powered on."
    test_client.app.state.device_connector.failures[("ios-lab-1", "retrieve")] = [
        DeviceUnreachableError(message)
    ]

    [result] = _push(test_client, [device["id"]])

    assert result["status"] == "unreachable"
    assert result["error"] == message
    assert result["before_version"] is None
    assert test_client.get(f"/api/v1/devices/{device['id']}/config/versions").json() == []
    assert [outcome for outcome, _ in _change_audit(testing_session)] == ["failed"]


def test_r3_5_failed_read_back_after_apply_is_unverified_not_failed(client):
    """Fault injection in phase 3: the change IS on the device, so it must not say 'failed'."""
    test_client, testing_session = client
    device = _add_device(test_client)
    connector = test_client.app.state.device_connector
    connector.failures[("ios-lab-1", "retrieve")] = []  # first retrieve succeeds

    def fail_second_retrieve(dev, config, original=connector.push):
        original(dev, config)
        connector.failures[("ios-lab-1", "retrieve")] = [
            DeviceUnreachableError("Lost the SSH session to ios-lab-1")
        ]

    connector.push = fail_second_retrieve

    [result] = _push(test_client, [device["id"]])

    assert result["status"] == "unverified"
    assert result["before_version"] == 1
    assert result["after_version"] is None
    assert "was applied to ios-lab-1" in result["error"]
    assert "ntp server" in connector.configurations["ios-lab-1"]
    assert [outcome for outcome, _ in _change_audit(testing_session)] == ["started", "unverified"]


def test_5_3_3_unexpected_errors_are_not_shown_raw_but_are_audited(client):
    """SRS 5.3.3: the operator sees an actionable message; the audit log keeps the details."""
    test_client, testing_session = client
    device = _add_device(test_client)
    test_client.app.state.device_connector.failures[("ios-lab-1", "push")] = [
        ValueError("internal parser state 0x2f")
    ]

    [result] = _push(test_client, [device["id"]])

    assert result["status"] == "failed"
    assert "0x2f" not in result["error"] and "ValueError" not in result["error"]
    assert "audit log" in result["error"]
    assert result["before_version"] == 1  # the pre-push snapshot was kept
    outcome, detail = _change_audit(testing_session)[-1]
    assert outcome == "failed"
    assert detail == "ValueError: internal parser state 0x2f"


def test_r3_2_retrieve_failure_returns_actionable_502_and_is_audited(client):
    test_client, testing_session = client
    device = _add_device(test_client)
    test_client.app.state.device_connector.failures[("ios-lab-1", "retrieve")] = [
        RuntimeError("socket closed by peer at frame 12")
    ]

    response = test_client.post(f"/api/v1/devices/{device['id']}/config/retrieve")

    assert response.status_code == 502
    assert "frame 12" not in response.json()["detail"]
    assert "ios-lab-1" in response.json()["detail"]
    assert _change_audit(testing_session) == [
        ("failed", "RuntimeError: socket closed by peer at frame 12")
    ]
