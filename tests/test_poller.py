from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_session, make_engine
from app.main import app
from app.models import Alert, Device, DeviceState, InterfaceStatus, PollSample
from app.poller import ProbeResult, poll_all, poll_device
from app.schemas import as_utc

NOW = datetime(2026, 10, 13, 12, 30, 45, tzinfo=UTC)
PREFIX = "/api/v1/monitoring"


@pytest.fixture
def client(tmp_path, monkeypatch):
    test_engine = make_engine(f"sqlite:///{tmp_path / 'poller.db'}")
    Base.metadata.create_all(test_engine)
    testing_session = sessionmaker(bind=test_engine, expire_on_commit=False)
    with testing_session() as session:
        session.add_all(
            Device(id=index, name=f"router-{index}", management_ip=f"192.0.2.{index}")
            for index in (1, 2)
        )
        session.commit()

    def override_session():
        with testing_session() as session:
            yield session

    monkeypatch.setattr("app.monitoring.utc_now", lambda: NOW)
    monkeypatch.setattr("app.poller.utc_now", lambda: NOW)
    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as test_client:
        yield test_client, testing_session
    app.dependency_overrides.clear()
    Base.metadata.drop_all(test_engine)
    test_engine.dispose()


def test_failures_open_one_alert_and_recovery_resolves_it(client):
    test_client, testing_session = client
    with testing_session() as session:
        device = session.get(Device, 1)
        for failures in (1, 2, 3):
            polled_at = NOW - timedelta(minutes=4 - failures)
            poll_device(session, device, lambda _: ProbeResult(False), now=polled_at)
            session.commit()

            state = session.get(DeviceState, 1)
            assert state.state == ("up" if failures == 1 else "down")
            assert state.consecutive_failures == failures
            assert as_utc(state.last_poll_at) == polled_at
            alerts = list(session.scalars(select(Alert)))
            assert len(alerts) == (0 if failures == 1 else 1)
            if alerts:
                assert alerts[0].message == (
                    "router-1 is unreachable (2 consecutive failed polls)"
                )
                assert as_utc(alerts[0].raised_at) == NOW - timedelta(minutes=2)
                assert alerts[0].resolved_at is None
            assert len(list(session.scalars(select(PollSample)))) == failures

        assert len(test_client.get(f"{PREFIX}/alerts").json()) == 1
        poll_device(session, device, lambda _: ProbeResult(True), now=NOW)
        session.commit()

        assert state.state == "up"
        assert state.consecutive_failures == 0
        assert as_utc(state.last_poll_at) == NOW
        assert as_utc(alerts[0].resolved_at) == NOW
        samples = list(session.scalars(select(PollSample).order_by(PollSample.id)))
        assert [sample.reachable for sample in samples] == [False, False, False, True]

    response = test_client.get(f"{PREFIX}/alerts")
    assert response.status_code == 200
    assert response.json() == []


def test_success_resets_failures_before_another_failure(client):
    _, testing_session = client
    with testing_session() as session:
        device = session.get(Device, 1)
        for reachable in (False, True, False):
            poll_device(session, device, lambda _, reachable=reachable: ProbeResult(reachable))
        session.commit()

        state = session.get(DeviceState, 1)
        assert state.state == "up"
        assert state.consecutive_failures == 1
        assert list(session.scalars(select(Alert))) == []


def test_new_outage_opens_new_alert_after_recovery(client):
    _, testing_session = client
    with testing_session() as session:
        device = session.get(Device, 1)
        for reachable in (False, False, True, False, False):
            poll_device(session, device, lambda _, reachable=reachable: ProbeResult(reachable))
        session.commit()

        alerts = list(session.scalars(select(Alert).order_by(Alert.id)))
        assert len(alerts) == 2
        assert as_utc(alerts[0].resolved_at) == NOW
        assert alerts[1].resolved_at is None


def test_down_transition_does_not_duplicate_existing_open_alert(client):
    _, testing_session = client
    with testing_session() as session:
        session.add(Alert(device_id=1, message="Existing outage", raised_at=NOW))
        device = session.get(Device, 1)
        for _ in range(2):
            poll_device(session, device, lambda _: ProbeResult(False))
        session.commit()

        assert session.get(DeviceState, 1).state == "down"
        alerts = list(session.scalars(select(Alert)))
        assert len(alerts) == 1
        assert alerts[0].message == "Existing outage"


def test_probe_exception_counts_as_failed_poll(client):
    _, testing_session = client

    def failing_probe(device):
        raise RuntimeError("simulated probe failure")

    with testing_session() as session:
        device = session.get(Device, 1)
        poll_device(session, device, failing_probe)
        session.commit()

        state = session.get(DeviceState, 1)
        assert state.state == "up"
        assert state.consecutive_failures == 1
        sample = session.scalar(select(PollSample))
        assert sample.reachable is False
        assert as_utc(sample.polled_at) == NOW
        assert (sample.rtt_ms, sample.cpu_pct, sample.memory_pct) == (None, None, None)
        assert (sample.in_bps, sample.out_bps) == (None, None)


def test_poll_all_continues_after_probe_exception(client):
    _, testing_session = client
    probed = []

    def probe(device):
        probed.append(device.id)
        if device.id == 1:
            raise RuntimeError("simulated probe failure")
        return ProbeResult(True, cpu_pct=25)

    for _ in range(2):
        poll_all(testing_session, probe)

    assert probed == [1, 2, 1, 2]
    with testing_session() as session:
        failed = session.get(DeviceState, 1)
        healthy = session.get(DeviceState, 2)
        assert (failed.state, failed.consecutive_failures) == ("down", 2)
        assert (healthy.state, healthy.consecutive_failures) == ("up", 0)
        samples = list(session.scalars(select(PollSample).order_by(PollSample.id)))
        assert [sample.device_id for sample in samples] == [1, 2, 1, 2]
        assert [sample.reachable for sample in samples] == [False, True, False, True]
        assert [alert.device_id for alert in session.scalars(select(Alert))] == [1]


def test_interfaces_replace_only_polled_device_and_none_preserves_rows(client):
    test_client, testing_session = client
    with testing_session() as session:
        session.add_all(
            [
                InterfaceStatus(device_id=1, index=1, name="Old", oper_status="down"),
                InterfaceStatus(device_id=1, index=2, name="Removed", oper_status="up"),
                InterfaceStatus(device_id=2, index=1, name="Other", oper_status="up"),
            ]
        )
        session.commit()
        device = session.get(Device, 1)
        result = ProbeResult(
            True,
            interfaces=[
                {"index": 1, "name": "Gi0/1", "oper_status": "up", "speed_mbps": 1000},
                {"index": 3, "name": "Gi0/3", "oper_status": "down"},
            ],
        )
        poll_device(session, device, lambda _: result)
        session.commit()
        poll_device(session, device, lambda _: ProbeResult(False))
        session.commit()

        response = test_client.get(f"{PREFIX}/devices/1/interfaces")
        assert response.status_code == 200
        assert response.json() == [
            {"index": 1, "name": "Gi0/1", "oper_status": "up", "speed_mbps": 1000},
            {"index": 3, "name": "Gi0/3", "oper_status": "down", "speed_mbps": None},
        ]

        poll_device(session, device, lambda _: ProbeResult(True, interfaces=[]))
        session.commit()

    assert test_client.get(f"{PREFIX}/devices/1/interfaces").json() == []
    assert test_client.get(f"{PREFIX}/devices/2/interfaces").json() == [
        {"index": 1, "name": "Other", "oper_status": "up", "speed_mbps": None}
    ]


def test_polled_samples_appear_in_metrics(client):
    test_client, testing_session = client
    with testing_session() as session:
        poll_device(
            session,
            session.get(Device, 1),
            lambda _: ProbeResult(
                True, rtt_ms=5.5, cpu_pct=20, memory_pct=40, in_bps=100, out_bps=200
            ),
        )
        session.commit()
        sample = session.scalar(select(PollSample))
        assert sample.device_id == 1
        assert as_utc(sample.polled_at) == NOW
        assert sample.reachable is True
        assert sample.rtt_ms == 5.5
        assert sample.memory_pct == 40

    response = test_client.get(f"{PREFIX}/metrics", params={"window": "1h"})

    assert response.status_code == 200
    assert response.json() == {
        "devices_up": [{"t": "2026-10-13T12:30:00Z", "value": 1}],
        "cpu_avg": [{"t": "2026-10-13T12:30:00Z", "value": 20}],
        "throughput_in_bps": [{"t": "2026-10-13T12:30:00Z", "value": 100}],
        "throughput_out_bps": [{"t": "2026-10-13T12:30:00Z", "value": 200}],
    }
