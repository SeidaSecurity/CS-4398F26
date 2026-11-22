import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, NotRequired, Protocol, TypedDict

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import (
    Alert,
    Device,
    DeviceState,
    InterfaceStatus,
    MetricAlert,
    PollSample,
    utc_now,
)

logger = logging.getLogger(__name__)
DEFAULT_CPU_ALERT_PERCENT = 90.0


class ProbeInterface(TypedDict):
    index: int
    name: str
    oper_status: Literal["up", "down"]
    speed_mbps: NotRequired[float | None]


@dataclass
class ProbeResult:
    reachable: bool
    rtt_ms: float | None = None
    cpu_pct: float | None = None
    memory_pct: float | None = None
    in_bps: float | None = None
    out_bps: float | None = None
    interfaces: list[ProbeInterface] | None = None


class Probe(Protocol):
    def __call__(self, device: Device) -> ProbeResult: ...


def cpu_alert_threshold() -> float:
    """CPU_ALERT_PERCENT (0 < value <= 100), else the default 90 (R2.5)."""
    raw = os.getenv("CPU_ALERT_PERCENT")
    if raw is None:
        return DEFAULT_CPU_ALERT_PERCENT
    try:
        value = float(raw)
    except ValueError:
        value = -1.0
    if not 0 < value <= 100:
        logger.warning(
            "CPU_ALERT_PERCENT=%r is not a percentage between 0 and 100; using %s",
            raw,
            DEFAULT_CPU_ALERT_PERCENT,
        )
        return DEFAULT_CPU_ALERT_PERCENT
    return value


def _open_alerts(session: Session, device_id: int) -> list[tuple[Alert, MetricAlert | None]]:
    rows = session.execute(
        select(Alert, MetricAlert)
        .outerjoin(MetricAlert, MetricAlert.alert_id == Alert.id)
        .where(Alert.device_id == device_id, Alert.resolved_at.is_(None))
    )
    return [(alert, mark) for alert, mark in rows]


def _check_cpu(
    session: Session, device: Device, cpu_pct: float, threshold: float, now: datetime
) -> None:
    """Raise one CPU alert at CPU >= threshold; resolve it once CPU drops below (P-008)."""
    open_cpu = [a for a, m in _open_alerts(session, device.id) if m and m.metric == "cpu"]
    if cpu_pct >= threshold and not open_cpu:
        alert = Alert(
            device_id=device.id,
            message=f"{device.name} CPU at {cpu_pct:.1f}% (alert threshold {threshold:g}%)",
            raised_at=now,
        )
        session.add(alert)
        session.flush()
        session.add(MetricAlert(alert_id=alert.id, metric="cpu", threshold=threshold))
    elif cpu_pct < threshold:
        for alert in open_cpu:
            alert.resolved_at = now


def poll_device(
    session: Session,
    device: Device,
    probe: Probe,
    now: datetime | None = None,
    cpu_threshold: float | None = None,
) -> None:
    """Record a poll in the caller's transaction; probe exceptions count as failures."""
    now = now or utc_now()
    threshold = cpu_alert_threshold() if cpu_threshold is None else cpu_threshold
    try:
        result = probe(device)
    except Exception:
        result = ProbeResult(reachable=False)

    session.add(
        PollSample(
            device_id=device.id,
            polled_at=now,
            reachable=result.reachable,
            rtt_ms=result.rtt_ms,
            cpu_pct=result.cpu_pct,
            memory_pct=result.memory_pct,
            in_bps=result.in_bps,
            out_bps=result.out_bps,
        )
    )
    state = session.get(DeviceState, device.id)
    if state is None:
        state = DeviceState(device_id=device.id, state="up", consecutive_failures=0)
        session.add(state)
    previous_state = state.state
    state.last_poll_at = now
    if result.reachable:
        state.consecutive_failures = 0
        state.state = "up"
    else:
        state.consecutive_failures += 1
        if state.consecutive_failures >= 2:
            state.state = "down"

    if state.state != previous_state:
        # Device-down alerts only: metric alerts are handled separately (checkpoint F).
        open_alerts = [a for a, mark in _open_alerts(session, device.id) if mark is None]
        if state.state == "down" and not open_alerts:
            session.add(
                Alert(
                    device_id=device.id,
                    message=(
                        f"{device.name} is unreachable "
                        f"({state.consecutive_failures} consecutive failed polls)"
                    ),
                    raised_at=now,
                )
            )
        elif state.state == "up":
            for alert in open_alerts:
                alert.resolved_at = now

    if result.reachable and result.cpu_pct is not None:
        _check_cpu(session, device, result.cpu_pct, threshold, now)

    if result.interfaces is not None:
        session.execute(delete(InterfaceStatus).where(InterfaceStatus.device_id == device.id))
        session.add_all(
            InterfaceStatus(device_id=device.id, **interface) for interface in result.interfaces
        )
    session.flush()


def poll_all(session_factory: Callable[[], Session], probe: Probe) -> None:
    """Poll every device and commit each result, continuing after probe failures."""
    with session_factory() as session:
        devices = list(session.scalars(select(Device).order_by(Device.id)))
        for device in devices:
            poll_device(session, device, probe)
            session.commit()
