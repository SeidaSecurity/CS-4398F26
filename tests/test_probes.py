import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app import main, probes
from app.database import Base, make_engine
from app.models import Device, PollSample
from app.poller import ProbeResult


@pytest.fixture(autouse=True)
def isolated_probes(monkeypatch):
    monkeypatch.delenv("SNMP_COMMUNITY", raising=False)
    monkeypatch.delenv("MONITORING_ENABLED", raising=False)
    monkeypatch.setenv("SYSLOG_ENABLED", "false")
    monkeypatch.setattr(probes, "_previous_readings", {})


@pytest.fixture
def device():
    return Device(id=1, name="router-1", management_ip="192.0.2.1")


@pytest.fixture
def snmp_data():
    return {
        "uptime": 1000,
        "cpu": {1: 20, 2: 40},
        "index": {2: 2, 1: 1},
        "name": {1: "Gi0/1", 2: "Gi0/2"},
        "status": {1: 1, 2: 2},
        "speed": {1: 1_000_000_000, 2: 100_000_000},
        "in_octets": {1: 1000, 2: 2000},
        "out_octets": {1: 3000, 2: 4000},
    }


@pytest.mark.parametrize("reachable", [True, False])
def test_ping_probe(monkeypatch, device, reachable):
    ping = Mock(return_value=SimpleNamespace(is_alive=reachable, avg_rtt=4.5))
    monkeypatch.setattr(probes.icmplib, "ping", ping)

    result = probes.ping_probe(device)

    ping.assert_called_once_with("192.0.2.1", count=1, timeout=1, privileged=False)
    assert result == ProbeResult(reachable, rtt_ms=4.5 if reachable else None)


@pytest.mark.parametrize("reachable", [True, False])
def test_combined_probe_skips_snmp_without_reachability_or_community(
    monkeypatch, device, reachable
):
    if not reachable:
        monkeypatch.setenv("SNMP_COMMUNITY", "public")
    monkeypatch.setattr(
        probes.icmplib, "ping", Mock(return_value=SimpleNamespace(is_alive=reachable, avg_rtt=3))
    )
    fetch = Mock(side_effect=AssertionError("SNMP must not run"))
    monkeypatch.setattr(probes, "_fetch_snmp", fetch)

    assert probes.combined_probe(device).reachable is reachable
    fetch.assert_not_called()


def test_snmp_error_keeps_device_reachable(monkeypatch, device):
    monkeypatch.setenv("SNMP_COMMUNITY", "public")
    monkeypatch.setattr(
        probes.icmplib, "ping", Mock(return_value=SimpleNamespace(is_alive=True, avg_rtt=3))
    )

    async def fail(address, community):
        raise TimeoutError("SNMP timed out")

    monkeypatch.setattr(probes, "_fetch_snmp", fail)

    assert probes.combined_probe(device) == ProbeResult(True, rtt_ms=3)


def test_snmp_metrics_and_throughput_delta(monkeypatch, device, snmp_data):
    monkeypatch.setenv("SNMP_COMMUNITY", "public")
    monkeypatch.setattr(
        probes.icmplib, "ping", Mock(return_value=SimpleNamespace(is_alive=True, avg_rtt=3))
    )

    async def fetch(address, community):
        assert (address, community) == ("192.0.2.1", "public")
        return snmp_data

    monkeypatch.setattr(probes, "_fetch_snmp", fetch)
    times = iter([10.0, 12.0])
    monkeypatch.setattr(probes, "monotonic", lambda: next(times))

    first = probes.combined_probe(device)
    assert (first.reachable, first.rtt_ms, first.cpu_pct) == (True, 3, 30)
    assert (first.in_bps, first.out_bps) == (None, None)
    assert first.interfaces == [
        {"index": 1, "name": "Gi0/1", "oper_status": "up", "speed_mbps": 1000},
        {"index": 2, "name": "Gi0/2", "oper_status": "down", "speed_mbps": 100},
    ]
    snmp_data["uptime"] += 200
    snmp_data["in_octets"] = {1: 1500, 2: 3000}
    snmp_data["out_octets"] = {1: 4000, 2: 6000}

    second = probes.combined_probe(device)

    assert (second.in_bps, second.out_bps) == (6000, 12000)


@pytest.mark.parametrize("reset", ["uptime", "counters", "device"])
def test_snmp_reset_does_not_report_invalid_rates(monkeypatch, device, snmp_data, reset):
    async def fetch(address, community):
        return snmp_data

    monkeypatch.setattr(probes, "_fetch_snmp", fetch)
    probes.snmp_probe(device, "public")
    if reset == "uptime":
        snmp_data["uptime"] = 1
    elif reset == "counters":
        snmp_data["in_octets"][1] = 0
    else:
        device = Device(id=2, name="router-2", management_ip="192.0.2.2")

    result = probes.snmp_probe(device, "public")

    assert (result.in_bps, result.out_bps) == (None, None)


def test_monitoring_disabled_by_default(monkeypatch):
    poll = Mock(side_effect=AssertionError("Monitoring must not run"))
    monkeypatch.setattr(main, "poll_all", poll)

    with TestClient(main.app) as client:
        assert client.get("/health").status_code == 200

    poll.assert_not_called()


@pytest.fixture
def monitoring_database(tmp_path, monkeypatch):
    engine = make_engine(f"sqlite:///{tmp_path / 'probes.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as session:
        session.add(Device(id=1, name="router-1", management_ip="192.0.2.1"))
        session.commit()
    monkeypatch.setattr(main, "SessionLocal", sessions)
    monkeypatch.setenv("MONITORING_ENABLED", "true")
    monkeypatch.setenv("POLL_INTERVAL_SECONDS", "0.01")
    yield sessions
    engine.dispose()


def test_monitoring_lifespan_writes_samples(monkeypatch, monitoring_database):
    polled_again = threading.Event()
    calls = []

    def probe(device):
        calls.append(device.id)
        if len(calls) >= 2:
            polled_again.set()
        return ProbeResult(True, rtt_ms=2)

    monkeypatch.setattr(main, "combined_probe", probe)
    with TestClient(main.app) as client:
        assert client.get("/health").status_code == 200
        assert polled_again.wait(timeout=2)

    with monitoring_database() as session:
        samples = list(session.scalars(select(PollSample)))
        assert len(samples) >= 2
        assert all(sample.reachable and sample.rtt_ms == 2 for sample in samples)


def test_monitoring_shutdown_waits_for_active_poll(monkeypatch, monitoring_database):
    started = threading.Event()
    release = threading.Event()

    def probe(device):
        started.set()
        assert release.wait(timeout=2)
        return ProbeResult(True)

    monkeypatch.setattr(main, "combined_probe", probe)

    async def run():
        context = main.lifespan(main.app)
        await context.__aenter__()
        shutdown = None
        try:
            assert await asyncio.to_thread(started.wait, 2)
            shutdown = asyncio.create_task(context.__aexit__(None, None, None))
            await asyncio.sleep(0.02)
            assert not shutdown.done()
        finally:
            release.set()
            if shutdown is not None:
                await shutdown
            else:
                await context.__aexit__(None, None, None)

    asyncio.run(run())
    with monitoring_database() as session:
        assert session.scalar(select(PollSample)).reachable is True
