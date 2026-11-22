import asyncio
import logging
import os
from contextlib import asynccontextmanager, suppress
from dataclasses import asdict
from datetime import datetime

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import (
    PasswordPolicyError,
    UserValidationError,
    bootstrap_admin,
    current_user,
    enforce_access,
)
from app.auth_routes import router as auth_router
from app.config_diff import DiffTooLargeError, side_by_side
from app.config_service import ConfigurationService
from app.config_templates import TemplateRenderError, render_template
from app.configuration import DeviceError, NetmikoConnector, record_audit_event
from app.connection_test import ConnectionTester
from app.credentials import (
    CredentialKeyError,
    CredentialValidationError,
    StoredOrEnvironmentCredentials,
    store_credentials,
)
from app.database import Base, SessionLocal, engine, get_session
from app.dhcp.routes import router as dhcp_router
from app.dhcp.server import start_dhcp_service
from app.dns.routes import router as dns_router
from app.dns.server import start_dns_service
from app.models import AuditRecord, ConfigTemplate, ConfigVersion, Device, User, utc_now
from app.monitoring import router as monitoring_router
from app.poller import poll_all
from app.probes import combined_probe
from app.schemas import (
    AuditRecordRead,
    ConfigDiffRead,
    ConfigPushRequest,
    ConfigPushResult,
    ConfigTemplateCreate,
    ConfigTemplateRead,
    ConfigTemplateRenderRead,
    ConfigTemplateRenderRequest,
    ConfigTemplateUpdate,
    ConfigVersionDetail,
    ConfigVersionRead,
    ConnectionTestRead,
    ConnectionTestRequest,
    DeviceCreate,
    DeviceRead,
    DeviceUpdate,
    LogRecordRead,
)
from app.syslog import SyslogReceivers, list_logs
from app.user_routes import router as users_router

Base.metadata.create_all(bind=engine)

DEFAULT_POLL_INTERVAL_SECONDS = 60.0  # SRS R2.1


def poll_interval_seconds() -> float:
    """Return the configured poll interval, defaulting to 60 s as required by R2.1."""
    return float(os.getenv("POLL_INTERVAL_SECONDS", str(DEFAULT_POLL_INTERVAL_SECONDS)))


async def _run_monitoring(interval: float) -> None:
    while True:
        worker = asyncio.create_task(asyncio.to_thread(poll_all, SessionLocal, combined_probe))
        try:
            await asyncio.shield(worker)
        except asyncio.CancelledError:
            # Cancelling to_thread cannot stop its thread; let the transaction finish.
            await worker
            raise
        except Exception:
            logging.getLogger(__name__).exception("Monitoring poll failed")
        await asyncio.sleep(interval)


def _bootstrap_admin_from_env() -> None:
    """Create the first admin from env on startup (R7.4); never touches the DB if unset."""
    log = logging.getLogger(__name__)
    username, password = os.getenv("ADMIN_USERNAME"), os.getenv("ADMIN_PASSWORD")
    if not username or not password:
        log.warning(
            "ADMIN_USERNAME/ADMIN_PASSWORD are not set, so no first admin will be created. "
            "If no users exist yet, nobody can log in."
        )
        return
    try:
        with SessionLocal() as db:
            outcome = bootstrap_admin(db, username, password)
            db.commit()
        log.info("Admin bootstrap: %s", outcome)
    except (PasswordPolicyError, UserValidationError) as exc:
        log.error("ADMIN_USERNAME/ADMIN_PASSWORD rejected: %s Fix .env.lab and restart.", exc)


def _start_syslog() -> SyslogReceivers | None:
    """Start the syslog listeners, or log why not (no longer crashes startup; SRS 5.3.1)."""
    if os.getenv("SYSLOG_ENABLED", "false").lower() != "true":
        return None
    host = os.getenv("SYSLOG_HOST", "0.0.0.0")
    udp_port = int(os.getenv("SYSLOG_UDP_PORT", "514"))
    tcp_port = int(os.getenv("SYSLOG_TCP_PORT", "514"))
    try:
        receivers = SyslogReceivers(host, udp_port, tcp_port)
    except OSError as exc:
        logging.getLogger(__name__).error(
            "Syslog could not listen on %s (UDP %s / TCP %s): %s. Another program may be using "
            "the port: find it with 'Get-NetUDPEndpoint -LocalPort %s', or change "
            "SYSLOG_UDP_PORT/SYSLOG_TCP_PORT. The rest of the application keeps running.",
            host, udp_port, tcp_port, exc, udp_port,
        )
        return None
    receivers.start()
    return receivers


@asynccontextmanager
async def lifespan(app: FastAPI):
    _bootstrap_admin_from_env()
    # Each network service starts independently: if one can't bind its port, it logs why and
    # the others keep running (SRS 5.3.1). app.state exposes what actually started.
    app.state.syslog_receivers = receivers = _start_syslog()
    app.state.dns_service = dns_service = (
        start_dns_service(
            SessionLocal,
            os.getenv("DNS_HOST", "0.0.0.0"),
            int(os.getenv("DNS_PORT", "53")),
        )
        if os.getenv("DNS_ENABLED", "false").lower() == "true"
        else None
    )
    app.state.dhcp_service = dhcp_service = (
        start_dhcp_service(
            SessionLocal,
            os.getenv("DHCP_SERVER_IP", ""),
            bind_host=os.getenv("DHCP_BIND_HOST") or None,
            port=int(os.getenv("DHCP_PORT", "67")),
        )
        if os.getenv("DHCP_ENABLED", "false").lower() == "true"
        else None
    )
    app.state.device_connector = NetmikoConnector(StoredOrEnvironmentCredentials())
    monitoring_task = None
    try:
        if os.getenv("MONITORING_ENABLED", "false").lower() == "true":
            monitoring_task = asyncio.create_task(
                _run_monitoring(poll_interval_seconds())
            )
        yield
    finally:
        try:
            if monitoring_task:
                monitoring_task.cancel()
                with suppress(asyncio.CancelledError):
                    await monitoring_task
        finally:
            if receivers:
                receivers.stop()
            if dns_service:
                dns_service.stop()
            if dhcp_service:
                dhcp_service.stop()


app = FastAPI(
    title="Network Management API",
    version="0.1.0",
    lifespan=lifespan,
    dependencies=[Depends(enforce_access)],  # central access policy (R7.1, R7.2)
)
app.include_router(monitoring_router)
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(dns_router)
app.include_router(dhcp_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


CREDENTIAL_FIELDS = {"username", "password", "secret"}


def _apply_credentials(
    session: Session,
    device: Device,
    username: str | None,
    password: str | None,
    secret: str | None,
) -> bool:
    """Store credentials sent with a create/update (R1.1). Returns True if anything changed."""
    if not (username or password or secret):
        return False
    existing = device.credential
    if not password:
        if existing is None:
            raise CredentialValidationError(
                "Give both a username and a password to store credentials for this device."
            )
        if username:
            existing.username = username.strip()  # rename only; password stays encrypted
        return bool(username)
    kept_secret = existing.secret_ciphertext if existing is not None and not secret else None
    name = username or (existing.username if existing is not None else "")
    if not name:
        raise CredentialValidationError(
            "Give both a username and a password to store credentials for this device."
        )
    record = store_credentials(session, device, name, password, secret)
    if kept_secret is not None:
        record.secret_ciphertext = kept_secret  # enable secret unchanged when not re-entered
    return True


def _credential_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, CredentialKeyError):
        return HTTPException(status_code=503, detail=str(exc))  # server misconfiguration
    return HTTPException(status_code=422, detail=str(exc))


@app.post("/api/v1/devices", response_model=DeviceRead, status_code=201)
def create_device(
    payload: DeviceCreate,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    device = Device(**payload.model_dump(exclude=CREDENTIAL_FIELDS))
    session.add(device)
    try:
        session.flush()  # a duplicate name fails here, before any credentials are stored
        _apply_credentials(session, device, payload.username, payload.password, payload.secret)
        detail = "with stored credentials" if device.has_credentials else ""
        record_audit_event(
            session, user.username, "device.create", "succeeded", device.name, detail
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="A device with that name already exists"
        ) from exc
    except (CredentialKeyError, CredentialValidationError) as exc:
        session.rollback()
        raise _credential_http_error(exc) from exc
    session.refresh(device)
    return device


@app.post("/api/v1/devices/test-connection", response_model=ConnectionTestRead)
def check_device_connection(
    payload: ConnectionTestRequest,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    """R1.3: check reachability and login with unsaved form values; nothing is saved.

    A sync route, so FastAPI runs the (up to ~18 s) device I/O in its thread pool.
    """
    tester = getattr(request.app.state, "connection_tester", None) or ConnectionTester()
    result = tester.run(**payload.model_dump())
    detail = "passed" if result.ok else f"failed at {result.failed_stage}"
    record_audit_event(
        session,
        user.username,
        "device.test_connection",
        "succeeded" if result.ok else "failed",
        f"{payload.management_ip}:{payload.ssh_port}",
        detail,
    )
    session.commit()
    return result.as_dict()


@app.get("/api/v1/devices", response_model=list[DeviceRead])
def get_devices(session: Session = Depends(get_session)):
    return list(session.scalars(select(Device).order_by(Device.name)))


@app.patch("/api/v1/devices/{device_id}", response_model=DeviceRead)
def update_device(
    device_id: int,
    payload: DeviceUpdate,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    device = session.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")
    for field, value in payload.model_dump(exclude_unset=True, exclude=CREDENTIAL_FIELDS).items():
        setattr(device, field, value)
    try:
        changed = _apply_credentials(
            session, device, payload.username, payload.password, payload.secret
        )
        detail = "credentials updated" if changed else ""
        record_audit_event(
            session, user.username, "device.update", "succeeded", device.name, detail
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="A device with that name already exists"
        ) from exc
    except (CredentialKeyError, CredentialValidationError) as exc:
        session.rollback()
        raise _credential_http_error(exc) from exc
    session.refresh(device)
    return device


@app.delete("/api/v1/devices/{device_id}", status_code=204)
def delete_device(
    device_id: int,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    device = session.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")
    record_audit_event(session, user.username, "device.delete", "succeeded", device.name)
    session.delete(device)
    session.commit()
    return Response(status_code=204)


@app.post("/api/v1/devices/{device_id}/config/retrieve", response_model=ConfigVersionRead)
def retrieve_configuration(
    device_id: int,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    device = session.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    try:
        return ConfigurationService(session, app.state.device_connector).retrieve(
            device, user.username
        )
    except DeviceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


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
    "/api/v1/devices/{device_id}/config/diff",
    response_model=ConfigDiffRead,
    response_model_exclude_none=True,
)
def get_configuration_diff(
    device_id: int,
    from_version: int = Query(alias="from", ge=1),
    to_version: int = Query(alias="to", ge=1),
    session: Session = Depends(get_session),
):
    """R3.4: diff two stored versions on the server (sync, so it runs in the thread pool)."""
    if session.get(Device, device_id) is None:
        raise HTTPException(status_code=404, detail="Device not found")
    records = {}
    for number in (from_version, to_version):
        record = session.scalar(
            select(ConfigVersion).where(
                ConfigVersion.device_id == device_id, ConfigVersion.version == number
            )
        )
        if record is None:
            raise HTTPException(
                status_code=404, detail=f"Configuration version {number} not found"
            )
        records[number] = record
    left, right = records[from_version], records[to_version]
    try:
        diff = side_by_side(left.configuration, right.configuration)
    except DiffTooLargeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"from_version": left, "to_version": right, **diff}


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


@app.get(
    "/api/v1/configuration-templates",
    response_model=list[ConfigTemplateRead],
)
def list_configuration_templates(session: Session = Depends(get_session)):
    return list(
        session.scalars(select(ConfigTemplate).order_by(ConfigTemplate.name, ConfigTemplate.id))
    )


@app.post(
    "/api/v1/configuration-templates",
    response_model=ConfigTemplateRead,
    status_code=201,
)
def create_configuration_template(
    payload: ConfigTemplateCreate,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    template = ConfigTemplate(**payload.model_dump())
    session.add(template)
    try:
        record_audit_event(
            session,
            user.username,
            "template.create",
            "succeeded",
            detail=f"Template '{template.name}'",
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="A configuration template with that name already exists"
        ) from exc
    session.refresh(template)
    return template


@app.post(
    "/api/v1/configuration-templates/render",
    response_model=ConfigTemplateRenderRead,
)
def render_configuration_template(payload: ConfigTemplateRenderRequest):
    try:
        configuration = render_template(payload.configuration, payload.variables)
    except TemplateRenderError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ConfigTemplateRenderRead(configuration=configuration)


@app.patch(
    "/api/v1/configuration-templates/{template_id}",
    response_model=ConfigTemplateRead,
)
def update_configuration_template(
    template_id: int,
    payload: ConfigTemplateUpdate,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    template = session.get(ConfigTemplate, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Configuration template not found")
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(template, field, value)
    template.updated_at = utc_now()
    try:
        record_audit_event(
            session,
            user.username,
            "template.update",
            "succeeded",
            detail=f"Template '{template.name}': changed {', '.join(sorted(changes))}",
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="A configuration template with that name already exists"
        ) from exc
    session.refresh(template)
    return template


@app.delete("/api/v1/configuration-templates/{template_id}", status_code=204)
def delete_configuration_template(
    template_id: int,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    template = session.get(ConfigTemplate, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Configuration template not found")
    record_audit_event(
        session, user.username, "template.delete", "succeeded", detail=f"Template '{template.name}'"
    )
    session.delete(template)
    session.commit()
    return Response(status_code=204)


@app.post(
    "/api/v1/devices/{device_id}/config/versions/{version}/restore",
    response_model=ConfigPushResult,
)
def restore_configuration(
    device_id: int,
    version: int,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    device = session.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")
    target = session.scalar(
        select(ConfigVersion).where(
            ConfigVersion.device_id == device_id,
            ConfigVersion.version == version,
        )
    )
    if target is None:
        raise HTTPException(status_code=404, detail="Configuration version not found")
    result = ConfigurationService(session, app.state.device_connector).rollback(
        device, target, user.username
    )
    return ConfigPushResult(**asdict(result))


@app.post("/api/v1/configurations/push", response_model=list[ConfigPushResult])
def push_configuration(
    payload: ConfigPushRequest,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    results = ConfigurationService(session, app.state.device_connector).push(
        payload.device_ids, payload.configuration, user.username
    )
    return [ConfigPushResult(**asdict(result)) for result in results]


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
