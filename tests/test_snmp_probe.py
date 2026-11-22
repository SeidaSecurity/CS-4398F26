"""SNMP metric parsing (R2.3): CPU (HOST-RESOURCES or Cisco), memory (Cisco pools), interfaces
and throughput. The SNMP fetch is faked (SRS 8.3); no packets are sent.
"""

import pytest

from app import probes
from app.models import Device
from app.poller import ProbeResult


def _data(**overrides):
    data = {
        "uptime": 1000,
        "cpu": {},
        "cisco_cpu": {},
        "mem_used": {},
        "mem_free": {},
        "index": {1: 1, 2: 2},
        "name": {1: "Gi0/0", 2: "Gi0/1"},
        "status": {1: 1, 2: 2},
        "speed": {1: 1_000_000_000, 2: 1_000_000_000},
        "in_octets": {1: 1000, 2: 0},
        "out_octets": {1: 2000, 2: 0},
    }
    data.update(overrides)
    return data


@pytest.fixture
def device():
    return Device(id=7, name="ios-lab-1", management_ip="192.0.2.11")


@pytest.fixture
def fake_fetch(monkeypatch):
    replies = []

    async def fetch(address, community):
        return replies.pop(0)

    monkeypatch.setattr(probes, "_fetch_snmp", fetch)
    probes._previous_readings.clear()
    return replies


def test_r2_3_cisco_cpu_and_memory(device, fake_fetch):
    fake_fetch.append(
        _data(cisco_cpu={1: 37}, mem_used={1: 30_000_000, 2: 5_000_000},
              mem_free={1: 60_000_000, 2: 5_000_000})
    )
    result = probes.snmp_probe(device, "community")
    assert result.cpu_pct == 37
    assert result.memory_pct == pytest.approx(35_000_000 / 100_000_000 * 100)


def test_r2_3_host_resources_cpu_preferred_and_averaged(device, fake_fetch):
    fake_fetch.append(_data(cpu={1: 10, 2: 30}, cisco_cpu={1: 99}))
    assert probes.snmp_probe(device, "c").cpu_pct == 20


def test_r2_3_no_cpu_or_memory_tables(device, fake_fetch):
    fake_fetch.append(_data())
    result = probes.snmp_probe(device, "c")
    assert result.cpu_pct is None and result.memory_pct is None


def test_r2_3_memory_with_zero_total_is_none(device, fake_fetch):
    fake_fetch.append(_data(mem_used={1: 0}, mem_free={1: 0}))
    assert probes.snmp_probe(device, "c").memory_pct is None


def test_r2_3_interfaces_and_throughput(device, fake_fetch, monkeypatch):
    clock = iter([100.0, 110.0])
    monkeypatch.setattr(probes, "monotonic", lambda: next(clock))
    fake_fetch.append(_data())
    fake_fetch.append(_data(uptime=2000, in_octets={1: 11_000, 2: 0}, out_octets={1: 4_500, 2: 0}))
    first = probes.snmp_probe(device, "c")
    assert first.in_bps is None  # first reading is only a baseline
    assert [i["oper_status"] for i in first.interfaces] == ["up", "down"]
    assert first.interfaces[0]["speed_mbps"] == 1000
    second = probes.snmp_probe(device, "c")
    assert second.in_bps == pytest.approx(10_000 * 8 / 10)
    assert second.out_bps == pytest.approx(2_500 * 8 / 10)


def test_r2_3_counter_reset_gives_no_negative_rate(device, fake_fetch, monkeypatch):
    clock = iter([100.0, 110.0])
    monkeypatch.setattr(probes, "monotonic", lambda: next(clock))
    fake_fetch.append(_data())
    fake_fetch.append(_data(uptime=2000, in_octets={1: 10, 2: 0}))
    probes.snmp_probe(device, "c")
    assert probes.snmp_probe(device, "c").in_bps is None


def test_r2_3_combined_probe(device, monkeypatch):
    monkeypatch.setattr(probes, "ping_probe", lambda d: ProbeResult(reachable=True, rtt_ms=2.5))
    monkeypatch.setattr(probes, "snmp_probe", lambda d, c: ProbeResult(reachable=True, cpu_pct=5))
    monkeypatch.setenv("SNMP_COMMUNITY", "c")
    result = probes.combined_probe(device)
    assert (result.cpu_pct, result.rtt_ms) == (5, 2.5)

    def broken(d, c):
        raise RuntimeError("timeout")

    monkeypatch.setattr(probes, "snmp_probe", broken)
    assert probes.combined_probe(device).cpu_pct is None  # SNMP failure: ping result only
    monkeypatch.delenv("SNMP_COMMUNITY")
    assert probes.combined_probe(device).rtt_ms == 2.5
    monkeypatch.setattr(probes, "ping_probe", lambda d: ProbeResult(reachable=False))
    assert probes.combined_probe(device).reachable is False
