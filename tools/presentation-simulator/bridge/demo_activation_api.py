"""Local-only, opt-in four-device presentation Inventory orchestration.

The independent simulator calls this API with a random token. It does not touch
real network inventory outside the presentation database.
"""
from __future__ import annotations
import hmac
import os
from datetime import UTC, datetime
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_session
from app.models import Device, DeviceState, InterfaceStatus, TopologyLink
from app.credentials import store_credentials

router = APIRouter(prefix="/api/v1/demo", tags=["opt-in presentation"])
NODES = (
    ("Primary-R1", 2222, True),
    ("Worker-R2", 2232, True),
    ("Worker-R3", 2242, True),
    ("Standby-R4", 2252, False),
)

def guard(request: Request, token: str | None) -> None:
    configured = os.getenv("CS4398_DEMO_ACTIVATION_TOKEN", "")
    if not configured or not token or not hmac.compare_digest(token, configured):
        raise HTTPException(403, "Demo token required")
    if request.client is None or request.client.host not in ("127.0.0.1", "::1", "testclient"):
        raise HTTPException(403, "Localhost only")

def update_state(session: Session, device: Device, up: bool) -> None:
    now = datetime.now(UTC)
    status = session.get(DeviceState, device.id)
    if status is None:
        session.add(DeviceState(device_id=device.id, state="up" if up else "down", last_poll_at=now, consecutive_failures=0))
    else:
        status.state = "up" if up else "down"
        status.last_poll_at = now
        status.consecutive_failures = 0
    iface = session.get(InterfaceStatus, (device.id, 1))
    if iface is None:
        session.add(InterfaceStatus(device_id=device.id, index=1, name="GigabitEthernet0/1", oper_status="up" if up else "down", speed_mbps=1000))
    else:
        iface.oper_status = "up" if up else "down"

def ensure_four(session: Session) -> list[Device]:
    all_nodes = []
    for name, port, initial_up in NODES:
        device = session.scalar(select(Device).where(Device.name == name))
        if device is None:
            device = Device(name=name, management_ip="127.0.0.1", platform="cisco_ios", ssh_port=port)
            session.add(device)
            session.flush()
            password = os.getenv("VROUTER_PASSWORD", "")
            if password:
                store_credentials(session, device, "labadmin", password)
        else:
            if device.management_ip != "127.0.0.1" or device.ssh_port != port:
                raise HTTPException(409, f"{name} conflicts with an existing Inventory device")
        all_nodes.append(device)
        # Existing active device is preserved; setup is idempotent but ensures standby starts down.
        if session.get(DeviceState, device.id) is None:
            update_state(session, device, initial_up)
    primary = all_nodes[0]
    for worker in all_nodes[1:]:
        a,b = sorted((primary.id, worker.id))
        if session.get(TopologyLink, (a,b)) is None:
            session.add(TopologyLink(a=a,b=b))
    return all_nodes

@router.post("/setup-four")
def setup_four(request: Request, x_demo_token: str | None = Header(default=None), session: Session = Depends(get_session)):
    guard(request, x_demo_token)
    devices = ensure_four(session)
    # Explicit reset of standby status at startup; never delete inventory.
    update_state(session, devices[3], False)
    session.commit()
    return {"ok": True, "devices": [{"id": d.id, "name": d.name, "ssh_port": d.ssh_port,
              "state": "up" if i < 3 else "down"} for i,d in enumerate(devices)], "links": 3}

@router.post("/activate-standby")
def activate_standby(request: Request, x_demo_token: str | None = Header(default=None), session: Session = Depends(get_session)):
    guard(request, x_demo_token)
    devices = ensure_four(session)
    update_state(session, devices[3], True)
    session.commit()
    return {"ok": True, "device": "Standby-R4", "state": "up", "device_id": devices[3].id}
