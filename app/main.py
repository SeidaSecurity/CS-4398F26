import os
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.configuration import NetmikoConnector, record_audit_event, save_config_version
from app.database import Base, engine, get_session
from app.models import AuditRecord, ConfigVersion, Device
from app.schemas import (
    AuditRecordRead,
    ConfigPushRequest,
    ConfigPushResult,
    ConfigVersionDetail,
    ConfigVersionRead,
    DeviceCreate,
    DeviceRead,
    DeviceUpdate,
    LogRecordRead,
)
from app.syslog import SyslogReceivers, list_logs

Base.metadata.create_all(bind=engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    receivers = None
    if os.getenv("SYSLOG_ENABLED", "false").lower() == "true":
        receivers = SyslogReceivers(
            os.getenv("SYSLOG_HOST", "0.0.0.0"),
            int(os.getenv("SYSLOG_UDP_PORT", "514")),
            int(os.getenv("SYSLOG_TCP_PORT", "514")),
        )
        receivers.start()
    app.state.device_connector = NetmikoConnector()
    yield
    if receivers:
        receivers.stop()


app = FastAPI(title="Network Management API", version="0.1.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/devices", response_model=DeviceRead, status_code=201)
def create_device(
    payload: DeviceCreate,
    operator: str = Query(default="unknown", min_length=1, max_length=120),
    session: Session = Depends(get_session),
):
    device = Device(**payload.model_dump())
    session.add(device)
    try:
        record_audit_event(session, operator, "device.create", "succeeded", device.name)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="A device with that name already exists"
        ) from exc
    session.refresh(device)
    return device


@app.get("/api/v1/devices", response_model=list[DeviceRead])
def get_devices(session: Session = Depends(get_session)):
    return list(session.scalars(select(Device).order_by(Device.name)))


@app.patch("/api/v1/devices/{device_id}", response_model=DeviceRead)
def update_device(
    device_id: int,
    payload: DeviceUpdate,
    operator: str = Query(default="unknown", min_length=1, max_length=120),
    session: Session = Depends(get_session),
):
    device = session.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(device, field, value)
    try:
        record_audit_event(session, operator, "device.update", "succeeded", device.name)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="A device with that name already exists"
        ) from exc
    session.refresh(device)
    return device


@app.delete("/api/v1/devices/{device_id}", status_code=204)
def delete_device(
    device_id: int,
    operator: str = Query(default="unknown", min_length=1, max_length=120),
    session: Session = Depends(get_session),
):
    device = session.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")
    record_audit_event(session, operator, "device.delete", "succeeded", device.name)
    session.delete(device)
    session.commit()
    return Response(status_code=204)


@app.post("/api/v1/devices/{device_id}/config/retrieve", response_model=ConfigVersionRead)
def retrieve_configuration(
    device_id: int,
    operator: str = Query(default="unknown", min_length=1, max_length=120),
    session: Session = Depends(get_session),
):
    device = session.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    try:
        configuration = app.state.device_connector.retrieve(device)
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Configuration retrieval failed: {exc}"
        ) from exc
    record = save_config_version(session, device.id, configuration, "retrieval", operator)
    record_audit_event(
        session,
        operator,
        "configuration.retrieve",
        "succeeded",
        device.name,
        f"Saved configuration version {record.version}",
    )
    session.commit()
    return record


@app.get("/api/v1/devices/{device_id}/config/versions", response_model=list[ConfigVersionRead])
def get_configuration_versions(device_id: int, session: Session = Depends(get_session)):
    if session.get(Device, device_id) is None:
        raise HTTPException(status_code=404, detail="Device not found")
    statement = (
        select(ConfigVersion)
        .where(ConfigVersion.device_id == device_id)
        .order_by(ConfigVersion.version.desc())
    )
    return list(session.scalars(statement))


@app.get(
    "/api/v1/devices/{device_id}/config/versions/{version}",
    response_model=ConfigVersionDetail,
)
def get_configuration_version(
    device_id: int,
    version: int,
    session: Session = Depends(get_session),
):
    record = session.scalar(
        select(ConfigVersion).where(
            ConfigVersion.device_id == device_id,
            ConfigVersion.version == version,
        )
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Configuration version not found")
    return record


@app.post("/api/v1/configurations/push", response_model=list[ConfigPushResult])
def push_configuration(payload: ConfigPushRequest, session: Session = Depends(get_session)):
    results = []
    for device_id in dict.fromkeys(payload.device_ids):
        device = session.get(Device, device_id)
        if device is None:
            results.append(
                ConfigPushResult(device_id=device_id, status="failed", error="Device not found")
            )
            continue
        try:
            before = app.state.device_connector.retrieve(device)
            before_version = save_config_version(
                session, device.id, before, "pre_push", payload.operator
            ).version
            record_audit_event(
                session,
                payload.operator,
                "configuration.push",
                "started",
                device.name,
                f"Saved pre-push configuration version {before_version}",
            )
            session.commit()
            app.state.device_connector.push(device, payload.configuration)
            after = app.state.device_connector.retrieve(device)
            after_version = save_config_version(
                session, device.id, after, "post_push", payload.operator
            ).version
            record_audit_event(
                session,
                payload.operator,
                "configuration.push",
                "succeeded",
                device.name,
                f"Configuration version {after_version} captured after push",
            )
            session.commit()
            results.append(
                ConfigPushResult(
                    device_id=device_id,
                    status="succeeded",
                    before_version=before_version,
                    after_version=after_version,
                )
            )
        except Exception as exc:
            session.rollback()
            record_audit_event(
                session,
                payload.operator,
                "configuration.push",
                "failed",
                device.name,
                f"{type(exc).__name__}: {exc}",
            )
            session.commit()
            results.append(
                ConfigPushResult(
                    device_id=device_id,
                    status="failed",
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
    return results


@app.get("/api/v1/logs", response_model=list[LogRecordRead])
def get_log_records(
    query: str | None = None,
    source: str | None = None,
    severity: int | None = Query(default=None, ge=0, le=7),
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    session: Session = Depends(get_session),
):
    if since and until and since > until:
        raise HTTPException(
            status_code=422,
            detail="'since' must be earlier than or equal to 'until'",
        )
    return list_logs(session, query, source, severity, since, until, limit)


@app.get("/api/v1/audit", response_model=list[AuditRecordRead])
def get_audit_records(
    limit: int = Query(default=100, ge=1, le=1000),
    session: Session = Depends(get_session),
):
    return list(
        session.scalars(select(AuditRecord).order_by(AuditRecord.occurred_at.desc()).limit(limit))
    )
