"""DNS zone and record API (R5.2). Thin: rules live in app/dns/zones.py.

Writes are admin-only and reads are open to viewers, via the central access policy
(auth.enforce_access). Every change is audited (R4.4).
"""

from collections.abc import Callable
from datetime import datetime
from typing import TypeVar

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import current_user
from app.configuration import record_audit_event
from app.database import get_session
from app.dns import zones
from app.models import DnsRecord, DnsZone, User

router = APIRouter(prefix="/api/v1/dns", tags=["dns"])
T = TypeVar("T")


class ZoneRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    default_ttl: int
    serial: int
    record_count: int
    created_at: datetime
    updated_at: datetime


class ZoneCreate(BaseModel):
    name: str = Field(min_length=1, max_length=254)
    default_ttl: int = zones.DEFAULT_TTL


class ZoneUpdate(BaseModel):
    default_ttl: int


class RecordRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    zone_id: int
    name: str
    fqdn: str
    rtype: str
    value: str
    ttl: int | None
    created_at: datetime


class RecordCreate(BaseModel):
    name: str = Field(min_length=1, max_length=254)
    rtype: str = Field(min_length=1, max_length=5)
    value: str = Field(min_length=1, max_length=254)
    ttl: int | None = None


class RecordUpdate(BaseModel):
    """Omitted fields stay as they are; `"ttl": null` resets to the zone default."""

    name: str | None = Field(default=None, min_length=1, max_length=254)
    value: str | None = Field(default=None, min_length=1, max_length=254)
    ttl: int | None = None


def _guard(action: Callable[[], T]) -> T:
    """Map rule errors to HTTP: syntax/range -> 422, clashes with existing data -> 409."""
    try:
        return action()
    except zones.DnsValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except zones.DnsConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _zone_or_404(db: Session, zone_id: int) -> DnsZone:
    zone = db.get(DnsZone, zone_id)
    if zone is None:
        raise HTTPException(status_code=404, detail="Zone not found. Refresh the zone list.")
    return zone


def _record_or_404(db: Session, record_id: int) -> DnsRecord:
    record = db.get(DnsRecord, record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Record not found. Refresh the record list.")
    return record


def _fqdn(record: DnsRecord) -> str:
    return record.zone.name if record.name == zones.APEX else f"{record.name}.{record.zone.name}"


def _zone_read(db: Session, zone: DnsZone) -> ZoneRead:
    count = db.scalar(select(func.count()).where(DnsRecord.zone_id == zone.id)) or 0
    return ZoneRead.model_validate({**zone.__dict__, "record_count": count})


def _record_read(record: DnsRecord) -> RecordRead:
    return RecordRead.model_validate({**record.__dict__, "fqdn": _fqdn(record)})


def _describe(record: DnsRecord) -> str:
    return f"{record.rtype} {_fqdn(record)} -> {record.value}"


# --- zones ---------------------------------------------------------------------------------------


@router.get("/zones", response_model=list[ZoneRead])
def list_zones(db: Session = Depends(get_session)):
    return [_zone_read(db, zone) for zone in db.scalars(select(DnsZone).order_by(DnsZone.name))]


@router.post("/zones", response_model=ZoneRead, status_code=201)
def create_zone(
    payload: ZoneCreate, user: User = Depends(current_user), db: Session = Depends(get_session)
):
    zone = _guard(lambda: zones.create_zone(db, payload.name, payload.default_ttl))
    record_audit_event(
        db, user.username, "dns.zone.create", "succeeded", detail=f"Zone '{zone.name}'"
    )
    db.commit()
    return _zone_read(db, zone)


@router.patch("/zones/{zone_id}", response_model=ZoneRead)
def update_zone(
    zone_id: int,
    payload: ZoneUpdate,
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
):
    zone = _zone_or_404(db, zone_id)
    _guard(lambda: zones.update_zone(db, zone, payload.default_ttl))
    record_audit_event(
        db,
        user.username,
        "dns.zone.update",
        "succeeded",
        detail=f"Zone '{zone.name}': default TTL {zone.default_ttl}",
    )
    db.commit()
    return _zone_read(db, zone)


@router.delete("/zones/{zone_id}", status_code=204)
def delete_zone(
    zone_id: int, user: User = Depends(current_user), db: Session = Depends(get_session)
) -> Response:
    zone = _zone_or_404(db, zone_id)
    count = len(zone.records)
    record_audit_event(
        db,
        user.username,
        "dns.zone.delete",
        "succeeded",
        detail=f"Zone '{zone.name}' ({count} records)",
    )
    db.delete(zone)
    db.commit()
    return Response(status_code=204)


# --- records -------------------------------------------------------------------------------------


@router.get("/zones/{zone_id}/records", response_model=list[RecordRead])
def list_records(zone_id: int, db: Session = Depends(get_session)):
    zone = _zone_or_404(db, zone_id)
    records = sorted(zone.records, key=lambda r: (r.name != zones.APEX, r.name, r.rtype, r.value))
    return [_record_read(record) for record in records]


@router.post("/zones/{zone_id}/records", response_model=RecordRead, status_code=201)
def create_record(
    zone_id: int,
    payload: RecordCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
):
    zone = _zone_or_404(db, zone_id)
    record = _guard(
        lambda: zones.create_record(
            db, zone, payload.name, payload.rtype, payload.value, payload.ttl
        )
    )
    record_audit_event(
        db, user.username, "dns.record.create", "succeeded", detail=_describe(record)
    )
    db.commit()
    return _record_read(record)


@router.patch("/records/{record_id}", response_model=RecordRead)
def update_record(
    record_id: int,
    payload: RecordUpdate,
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
):
    record = _record_or_404(db, record_id)
    sent = payload.model_fields_set
    for field in ("name", "value"):
        if field in sent and getattr(payload, field) is None:
            raise HTTPException(
                status_code=422, detail=f"'{field}' cannot be null; omit it instead."
            )
    _guard(
        lambda: zones.update_record(
            db,
            record,
            name=payload.name,
            value=payload.value,
            ttl=payload.ttl,
            clear_ttl="ttl" in sent and payload.ttl is None,
        )
    )
    record_audit_event(
        db, user.username, "dns.record.update", "succeeded", detail=_describe(record)
    )
    db.commit()
    return _record_read(record)


@router.delete("/records/{record_id}", status_code=204)
def delete_record(
    record_id: int, user: User = Depends(current_user), db: Session = Depends(get_session)
) -> Response:
    record = _record_or_404(db, record_id)
    record_audit_event(
        db, user.username, "dns.record.delete", "succeeded", detail=_describe(record)
    )
    zones.delete_record(db, record)
    db.commit()
    return Response(status_code=204)
