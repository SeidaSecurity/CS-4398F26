from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_session, make_engine
from app.main import app
from app.models import (
    Alert,
    ConfigVersion,
    Device,
    DeviceState,
    InterfaceStatus,
    PollSample,
    TopologyLink,
)

NOW = datetime(2026, 10, 13, 12, 30, 45, tzinfo=UTC)
PREFIX = "/api/v1/monitoring"
EMPTY_NETWORK_METRICS = {
    "devices_up": [],
    "cpu_avg": [],
    "throughput_in_bps": [],
    "throughput_out_bps": [],
}
EMPTY_DEVICE_METRICS = {
    "cpu": [],
    "memory": [],
    "throughput_in_bps": [],
    "throughput_out_bps": [],
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    test_engine = make_engine(f"sqlite:///{tmp_path / 'monitoring.db'}")
    Base.metadata.create_all(test_engine)
    testing_session = sessionmaker(bind=test_engine, expire_on_commit=False)

    def override_session():
        with testing_session() as session:
            yield session

    monkeypatch.setattr("app.monitoring.utc_now", lambda: NOW)
    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as test_client:
        yield test_client, testing_session
    app.dependency_overrides.clear()
    Base.metadata.drop_all(test_engine)
    test_engine.dispose()


@pytest.fixture
def devices(client):
    _, testing_session = client
    with testing_session() as session:
        session.add_all(
            Device(id=index, name=f"router-{index}", management_ip=f"192.0.2.{index}")
            for index in (1, 2, 3)
        )
        session.commit()


def test_status_only_includes_devices_with_state(client, devices):
    test_client, testing_session = client
    with testing_session() as session:
        session.add_all(
            [
                DeviceState(device_id=2, state="down", last_poll_at=NOW, consecutive_failures=3),
                DeviceState(device_id=1, state="up", last_poll_at=NOW, consecutive_failures=0),
            ]
        )
        session.commit()

    response = test_client.get(f"{PREFIX}/status")

    assert response.status_code == 200
    assert response.json() == [
        {
            "device_id": 1,
            "state": "up",
            "last_poll_at": "2026-10-13T12:30:45Z",
            "consecutive_failures": 0,
        },
        {
            "device_id": 2,
            "state": "down",
            "last_poll_at": "2026-10-13T12:30:45Z",
            "consecutive_failures": 3,
        },
    ]


def test_alerts_exclude_resolved_and_sort_newest_first(client, devices):
    test_client, testing_session = client
    with testing_session() as session:
        session.add_all(
            [
                Alert(id=1, device_id=1, message="Old alert", raised_at=NOW - timedelta(minutes=1)),
                Alert(id=2, device_id=2, message="New alert", raised_at=NOW),
                Alert(id=3, device_id=1, message="Resolved", raised_at=NOW, resolved_at=NOW),
            ]
        )
        session.commit()

    response = test_client.get(f"{PREFIX}/alerts")

    assert response.status_code == 200
    assert response.json() == [
        {"id": 2, "device_id": 2, "message": "New alert", "raised_at": "2026-10-13T12:30:45Z"},
        {"id": 1, "device_id": 1, "message": "Old alert", "raised_at": "2026-10-13T12:29:45Z"},
    ]


def test_topology_returns_plain_list(client, devices):
    test_client, testing_session = client
    with testing_session() as session:
        session.add_all([TopologyLink(a=2, b=3), TopologyLink(a=1, b=2)])
        session.commit()

    response = test_client.get(f"{PREFIX}/topology")

    assert response.status_code == 200
    assert response.json() == [{"a": 1, "b": 2}, {"a": 2, "b": 3}]


def test_interfaces_are_scoped_to_device_and_sorted(client, devices):
    test_client, testing_session = client
    with testing_session() as session:
        session.add_all(
            [
                InterfaceStatus(device_id=1, index=2, name="Gi0/2", oper_status="down"),
                InterfaceStatus(
                    device_id=1, index=1, name="Gi0/1", oper_status="up", speed_mbps=1000
                ),
                InterfaceStatus(device_id=2, index=1, name="Other", oper_status="up"),
            ]
        )
        session.commit()

    response = test_client.get(f"{PREFIX}/devices/1/interfaces")

    assert response.status_code == 200
    assert response.json() == [
        {"index": 1, "name": "Gi0/1", "oper_status": "up", "speed_mbps": 1000},
        {"index": 2, "name": "Gi0/2", "oper_status": "down", "speed_mbps": None},
    ]


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/status", []),
        ("/alerts", []),
        ("/topology", []),
        ("/devices/1/interfaces", []),
        ("/metrics", EMPTY_NETWORK_METRICS),
        ("/devices/1/metrics", EMPTY_DEVICE_METRICS),
    ],
)
def test_empty_monitoring_responses(client, devices, path, expected):
    test_client, _ = client

    response = test_client.get(f"{PREFIX}{path}")

    assert response.status_code == 200
    assert response.json() == expected


@pytest.mark.parametrize("endpoint", ["interfaces", "metrics"])
def test_unknown_device_returns_404(client, endpoint):
    test_client, _ = client

    response = test_client.get(f"{PREFIX}/devices/999/{endpoint}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Device not found"}


@pytest.mark.parametrize("path", ["/metrics", "/devices/1/metrics"])
@pytest.mark.parametrize("window", ["", "2h", "24H", "30d"])
def test_invalid_window_returns_422(client, devices, path, window):
    test_client, _ = client

    response = test_client.get(f"{PREFIX}{path}", params={"window": window})

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["query", "window"]


@pytest.mark.parametrize(
    ("window", "duration", "bucket_size", "bucket_start"),
    [
        ("1h", timedelta(hours=1), timedelta(minutes=1), NOW.replace(minute=29, second=0)),
        ("24h", timedelta(hours=24), timedelta(minutes=15), NOW.replace(minute=15, second=0)),
        ("7d", timedelta(days=7), timedelta(hours=2), NOW.replace(minute=0, second=0)),
    ],
)
def test_metrics_bucket_samples_and_skip_nulls(
    client, devices, window, duration, bucket_size, bucket_start
):
    test_client, testing_session = client
    previous_bucket = bucket_start - bucket_size
    with testing_session() as session:
        session.add_all(
            [
                PollSample(
                    device_id=1,
                    polled_at=bucket_start,
                    reachable=True,
                    cpu_pct=20,
                    memory_pct=40,
                    in_bps=100,
                    out_bps=200,
                ),
                PollSample(
                    device_id=1,
                    polled_at=bucket_start + timedelta(seconds=10),
                    reachable=True,
                    cpu_pct=40,
                    memory_pct=60,
                    in_bps=300,
                    out_bps=400,
                ),
                PollSample(
                    device_id=2,
                    polled_at=bucket_start,
                    reachable=True,
                    cpu_pct=60,
                    memory_pct=80,
                    in_bps=800,
                ),
                PollSample(device_id=1, polled_at=previous_bucket, reachable=False),
                PollSample(
                    device_id=1,
                    polled_at=NOW - duration - timedelta(seconds=1),
                    reachable=True,
                    cpu_pct=99,
                    memory_pct=99,
                    in_bps=9999,
                    out_bps=9999,
                ),
                PollSample(
                    device_id=1,
                    polled_at=NOW + timedelta(seconds=1),
                    reachable=True,
                    cpu_pct=99,
                    memory_pct=99,
                    in_bps=9999,
                    out_bps=9999,
                ),
            ]
        )
        session.commit()
    timestamp = bucket_start.isoformat().replace("+00:00", "Z")
    previous_timestamp = previous_bucket.isoformat().replace("+00:00", "Z")

    network = test_client.get(f"{PREFIX}/metrics", params={"window": window})
    device = test_client.get(f"{PREFIX}/devices/1/metrics", params={"window": window})

    assert network.status_code == 200
    assert network.json() == {
        "devices_up": [
            {"t": previous_timestamp, "value": 0},
            {"t": timestamp, "value": 2},
        ],
        "cpu_avg": [{"t": timestamp, "value": 40}],
        "throughput_in_bps": [{"t": timestamp, "value": 1000}],
        "throughput_out_bps": [{"t": timestamp, "value": 300}],
    }
    assert device.status_code == 200
    assert device.json() == {
        "cpu": [{"t": timestamp, "value": 30}],
        "memory": [{"t": timestamp, "value": 50}],
        "throughput_in_bps": [{"t": timestamp, "value": 200}],
        "throughput_out_bps": [{"t": timestamp, "value": 300}],
    }


def test_metrics_include_window_boundaries_and_zero_values(client, devices):
    test_client, testing_session = client
    with testing_session() as session:
        session.add_all(
            [
                PollSample(
                    device_id=1,
                    polled_at=NOW - timedelta(hours=1),
                    reachable=True,
                    cpu_pct=0,
                    memory_pct=0,
                    in_bps=0,
                    out_bps=0,
                ),
                PollSample(
                    device_id=1,
                    polled_at=NOW,
                    reachable=False,
                    cpu_pct=10,
                    memory_pct=20,
                    in_bps=30,
                    out_bps=40,
                ),
            ]
        )
        session.commit()

    network = test_client.get(f"{PREFIX}/metrics")
    device = test_client.get(f"{PREFIX}/devices/1/metrics")

    def points(first, last):
        return [
            {"t": "2026-10-13T11:30:00Z", "value": first},
            {"t": "2026-10-13T12:30:00Z", "value": last},
        ]

    assert network.status_code == 200
    assert network.json() == {
        "devices_up": points(1, 0),
        "cpu_avg": points(0, 10),
        "throughput_in_bps": points(0, 30),
        "throughput_out_bps": points(0, 40),
    }
    assert device.status_code == 200
    assert device.json() == {
        "cpu": points(0, 10),
        "memory": points(0, 20),
        "throughput_in_bps": points(0, 30),
        "throughput_out_bps": points(0, 40),
    }


@pytest.mark.parametrize("bulk_delete", [False, True])
def test_device_delete_cascades_all_monitoring_rows(client, devices, bulk_delete):
    test_client, testing_session = client
    with testing_session() as session:
        for device_id in (1, 2):
            session.add_all(
                [
                    PollSample(device_id=device_id, polled_at=NOW, reachable=True),
                    DeviceState(device_id=device_id, state="up", last_poll_at=NOW),
                    Alert(device_id=device_id, message="Test", raised_at=NOW),
                    InterfaceStatus(device_id=device_id, index=1, name="Gi0/1", oper_status="up"),
                    ConfigVersion(
                        device_id=device_id, version=1, configuration="test", source="test"
                    ),
                ]
            )
        session.add_all(
            [
                TopologyLink(a=1, b=2),
                TopologyLink(a=2, b=1),
                TopologyLink(a=2, b=3),
            ]
        )
        session.commit()

    if bulk_delete:
        # Exercise database cascades independently of SQLAlchemy relationships.
        with testing_session() as session:
            session.execute(delete(Device).where(Device.id == 1))
            session.commit()
    else:
        response = test_client.delete("/api/v1/devices/1")
        assert response.status_code == 204
        assert response.content == b""

    with testing_session() as session:
        assert session.get(Device, 1) is None
        for model in (PollSample, DeviceState, Alert, InterfaceStatus, ConfigVersion):
            assert [row.device_id for row in session.scalars(select(model))] == [2]
        assert [(link.a, link.b) for link in session.scalars(select(TopologyLink))] == [(2, 3)]
    assert test_client.get(f"{PREFIX}/devices/1/interfaces").status_code == 404
    assert test_client.get(f"{PREFIX}/devices/1/metrics").status_code == 404
