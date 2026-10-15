from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, NotRequired, Protocol, TypedDict

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import Alert, Device, DeviceState, InterfaceStatus, PollSample, utc_now


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


def poll_device(
    session: Session, device: Device, probe: Probe, now: datetime | None = None
) -> None:
    """Record a poll in the caller's transaction; probe exceptions count as failures."""
    now = now or utc_now()
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
        open_alerts = list(
            session.scalars(
                select(Alert).where(Alert.device_id == device.id, Alert.resolved_at.is_(None))
            )
        )
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
