import asyncio
import os
from dataclasses import dataclass
from time import monotonic
from typing import Any

import icmplib
from pysnmp.hlapi.v3arch.asyncio import (
    CommunityData,
    ContextData,
    ObjectIdentity,
    ObjectType,
    SnmpEngine,
    UdpTransportTarget,
    get_cmd,
    walk_cmd,
)

from app.models import Device
from app.poller import ProbeResult

SYS_UPTIME = "1.3.6.1.2.1.1.3.0"
SNMP_COLUMNS = {
    "cpu": "1.3.6.1.2.1.25.3.3.1.2",
    "index": "1.3.6.1.2.1.2.2.1.1",
    "name": "1.3.6.1.2.1.2.2.1.2",
    "status": "1.3.6.1.2.1.2.2.1.8",
    "speed": "1.3.6.1.2.1.2.2.1.5",
    "in_octets": "1.3.6.1.2.1.31.1.1.1.6",
    "out_octets": "1.3.6.1.2.1.31.1.1.1.10",
}
# Vendor tables (R2.3): walked when present; a device without them still reports the rest.
OPTIONAL_SNMP_COLUMNS = {
    "cisco_cpu": "1.3.6.1.4.1.9.9.109.1.1.1.1.8",  # CISCO-PROCESS-MIB cpmCPUTotal5minRev (%)
    "mem_used": "1.3.6.1.4.1.9.9.48.1.1.1.5",  # CISCO-MEMORY-POOL-MIB ciscoMemoryPoolUsed
    "mem_free": "1.3.6.1.4.1.9.9.48.1.1.1.6",  # CISCO-MEMORY-POOL-MIB ciscoMemoryPoolFree
}


@dataclass
class CounterReading:
    timestamp: float
    uptime: int
    counters: dict[int, tuple[int, int]]


_previous_readings: dict[tuple[int, str], CounterReading] = {}


def ping_probe(device: Device) -> ProbeResult:
    host = icmplib.ping(device.management_ip, count=1, timeout=1, privileged=False)
    return ProbeResult(reachable=host.is_alive, rtt_ms=host.avg_rtt if host.is_alive else None)


async def _fetch_snmp(address: str, community: str) -> dict[str, Any]:
    """Fetch numeric OIDs without depending on downloaded vendor MIBs."""
    engine = SnmpEngine()
    try:
        target = await UdpTransportTarget.create((address, 161), timeout=1, retries=0)
        args = (engine, CommunityData(community, mpModel=1), target, ContextData())
        error, status, _, bindings = await get_cmd(*args, ObjectType(ObjectIdentity(SYS_UPTIME)))
        if error or status:
            raise RuntimeError(f"SNMP GET failed: {error or status}")
        data: dict[str, Any] = {"uptime": int(bindings[0][1])}

        async def walk(oid: str) -> dict[int, Any]:
            column = {}
            async for error, status, _, bindings in walk_cmd(
                *args, ObjectType(ObjectIdentity(oid)), lexicographicMode=False
            ):
                if error or status:
                    raise RuntimeError(f"SNMP walk failed: {error or status}")
                for returned_oid, value in bindings:
                    column[int(returned_oid[-1])] = value
            return column

        for name, oid in SNMP_COLUMNS.items():
            data[name] = await walk(oid)
        for name, oid in OPTIONAL_SNMP_COLUMNS.items():
            try:
                data[name] = await walk(oid)
            except RuntimeError:
                data[name] = {}
        return data
    finally:
        engine.close_dispatcher()


def _cpu_percent(data: dict[str, Any]) -> float | None:
    """Average HOST-RESOURCES processor load; else the Cisco 5-minute CPU (IOS/IOSv)."""
    for column in ("cpu", "cisco_cpu"):
        loads = [int(value) for value in data.get(column, {}).values()]
        if loads:
            return sum(loads) / len(loads)
    return None


def _memory_percent(data: dict[str, Any]) -> float | None:
    """Used share of all Cisco memory pools (processor, I/O, ...)."""
    used = sum(int(value) for value in data.get("mem_used", {}).values())
    free = sum(int(value) for value in data.get("mem_free", {}).values())
    return used / (used + free) * 100 if used + free > 0 else None


def snmp_probe(device: Device, community: str) -> ProbeResult:
    data = asyncio.run(_fetch_snmp(device.management_ip, community))
    result = ProbeResult(
        reachable=True,
        cpu_pct=_cpu_percent(data),
        memory_pct=_memory_percent(data),
        interfaces=[
            {
                "index": int(index),
                "name": str(data["name"][index]),
                "oper_status": "up" if int(data["status"][index]) == 1 else "down",
                "speed_mbps": int(data["speed"][index]) / 1_000_000,
            }
            for index in sorted(data["index"])
        ],
    )
    counters = {
        index: (int(value), int(data["out_octets"][index]))
        for index, value in data["in_octets"].items()
        if index in data["out_octets"]
    }
    current = CounterReading(monotonic(), data["uptime"], counters)
    key = (device.id, device.management_ip)
    previous = _previous_readings.get(key)
    _previous_readings[key] = current
    if previous is not None and current.uptime >= previous.uptime:
        elapsed = current.timestamp - previous.timestamp
        common = counters.keys() & previous.counters.keys()
        deltas = [
            (
                counters[index][0] - previous.counters[index][0],
                counters[index][1] - previous.counters[index][1],
            )
            for index in common
        ]
        # Reboots and counter resets establish a new baseline rather than negative rates.
        if elapsed > 0 and deltas and all(i >= 0 and o >= 0 for i, o in deltas):
            result.in_bps = sum(i for i, _ in deltas) * 8 / elapsed
            result.out_bps = sum(o for _, o in deltas) * 8 / elapsed
    return result


def combined_probe(device: Device) -> ProbeResult:
    result = ping_probe(device)
    if not result.reachable:
        return result
    community = os.getenv("SNMP_COMMUNITY")
    if community:
        try:
            metrics = snmp_probe(device, community)
        except Exception:
            return result
        metrics.rtt_ms = result.rtt_ms
        return metrics
    return result
