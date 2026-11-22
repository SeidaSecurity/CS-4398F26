"""DHCP pool, reservation and lease API (R6.2, R6.3, R6.4). Thin: rules live in pools.py.

Writes are admin-only and reads are open to viewers via the central access policy
(auth.enforce_access). Every change is audited (R4.4).
"""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import current_user
from app.configuration import record_audit_event
from app.database import get_session
from app.dhcp import pools
from app.models import DhcpLease, DhcpPool, DhcpReservation, User
from app.schemas import PartialUpdate

router = APIRouter(prefix="/api/v1/dhcp", tags=["dhcp"])
T = TypeVar("T")


class PoolRead(BaseModel):
    id: int
    name: str
    subnet: str
    range_start: str
    range_end: str
    gateway: str
    dns_servers: list[str]
    domain: str
    lease_seconds: int
    reservation_count: int
    active_lease_count: int
    created_at: datetime
    updated_at: datetime


class PoolCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    subnet: str = Field(min_length=1, max_length=18)
    range_start: str = Field(min_length=1, max_length=15)
    range_end: str = Field(min_length=1, max_length=15)
    gateway: str = Field(min_length=1, max_length=15)
    dns_servers: list[str] = Field(min_length=1, max_length=pools.MAX_DNS_SERVERS)
    domain: str = Field(min_length=1, max_length=254)
    lease_seconds: int = 86_400


class PoolUpdate(PartialUpdate):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    subnet: str | None = Field(default=None, min_length=1, max_length=18)
    range_start: str | None = Field(default=None, min_length=1, max_length=15)
    range_end: str | None = Field(default=None, min_length=1, max_length=15)
    gateway: str | None = Field(default=None, min_length=1, max_length=15)
    dns_servers: list[str] | None = Field(
        default=None, min_length=1, max_length=pools.MAX_DNS_SERVERS
    )
    domain: str | None = Field(default=None, min_length=1, max_length=254)
    lease_seconds: int | None = None


class ReservationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    pool_id: int
    mac: str
    ip: str
    hostname: str | None
    created_at: datetime


class ReservationCreate(BaseModel):
    mac: str = Field(min_length=1, max_length=32)
    ip: str = Field(min_length=1, max_length=15)
    hostname: str | None = Field(default=None, max_length=254)


class LeaseRead(BaseModel):
    id: int
    pool_id: int
    pool_name: str
    mac: str
    ip: str
    hostname: str | None
    state: str
    expires_at: datetime


def _guard(action: Callable[[], T]) -> T:
    """Map rule errors to HTTP: syntax/range -> 422, clashes with existing data -> 409."""
    try:
        return action()
    except pools.DhcpValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except pools.DhcpConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _active(lease: DhcpLease) -> bool:
    expires = lease.expires_at
    expires = expires.replace(tzinfo=UTC) if expires.tzinfo is None else expires
    return expires > datetime.now(UTC)


def _pool_or_404(db: Session, pool_id: int) -> DhcpPool:
    pool = db.get(DhcpPool, pool_id)
    if pool is None:
        raise HTTPException(status_code=404, detail="Pool not found. Refresh the pool list.")
    return pool


def _pool_read(pool: DhcpPool) -> PoolRead:
    data: dict[str, Any] = {
        column: getattr(pool, column)
        for column in (
            "id",
            "name",
            "subnet",
            "range_start",
            "range_end",
            "gateway",
            "domain",
            "lease_seconds",
            "created_at",
            "updated_at",
        )
    }
    return PoolRead(
        **data,
        dns_servers=pools.dns_list(pool),
        reservation_count=len(pool.reservations),
        active_lease_count=sum(1 for lease in pool.leases if _active(lease)),
    )


def _lease_read(lease: DhcpLease) -> LeaseRead:
    return LeaseRead(
        id=lease.id,
        pool_id=lease.pool_id,
        pool_name=lease.pool.name,
        mac=lease.mac,
        ip=lease.ip,
        hostname=lease.hostname,
        state=lease.state,
        expires_at=lease.expires_at,
    )


# --- pools (R6.2) --------------------------------------------------------------------------------


@router.get("/pools", response_model=list[PoolRead])
def list_pools(db: Session = Depends(get_session)):
    return [_pool_read(pool) for pool in db.scalars(select(DhcpPool).order_by(DhcpPool.name))]


@router.post("/pools", response_model=PoolRead, status_code=201)
def create_pool(
    payload: PoolCreate, user: User = Depends(current_user), db: Session = Depends(get_session)
):
    pool = _guard(lambda: pools.create_pool(db, **payload.model_dump()))
    record_audit_event(
        db,
        user.username,
        "dhcp.pool.create",
        "succeeded",
        detail=f"Pool '{pool.name}' ({pool.subnet}, {pool.range_start}-{pool.range_end})",
    )
    db.commit()
    return _pool_read(pool)


@router.patch("/pools/{pool_id}", response_model=PoolRead)
def update_pool(
    pool_id: int,
    payload: PoolUpdate,
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
):
    pool = _pool_or_404(db, pool_id)
    changes = payload.model_dump(exclude_unset=True)
    _guard(lambda: pools.update_pool(db, pool, **changes))
    record_audit_event(
        db,
        user.username,
        "dhcp.pool.update",
        "succeeded",
        detail=f"Pool '{pool.name}': changed {', '.join(sorted(changes))}",
    )
    db.commit()
    return _pool_read(pool)


@router.delete("/pools/{pool_id}", status_code=204)
def delete_pool(
    pool_id: int, user: User = Depends(current_user), db: Session = Depends(get_session)
) -> Response:
    """Deletes the pool with its reservations and leases (checkpoint B: counts are audited)."""
    pool = _pool_or_404(db, pool_id)
    active = sum(1 for lease in pool.leases if _active(lease))
    record_audit_event(
        db,
        user.username,
        "dhcp.pool.delete",
        "succeeded",
        detail=f"Pool '{pool.name}' ({active} active leases, "
        f"{len(pool.reservations)} reservations)",
    )
    db.delete(pool)
    db.commit()
    return Response(status_code=204)


# --- reservations (R6.3) -------------------------------------------------------------------------


@router.get("/pools/{pool_id}/reservations", response_model=list[ReservationRead])
def list_reservations(pool_id: int, db: Session = Depends(get_session)):
    pool = _pool_or_404(db, pool_id)
    return sorted(pool.reservations, key=lambda r: tuple(int(part) for part in r.ip.split(".")))


@router.post("/pools/{pool_id}/reservations", response_model=ReservationRead, status_code=201)
def create_reservation(
    pool_id: int,
    payload: ReservationCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
):
    pool = _pool_or_404(db, pool_id)
    reservation = _guard(
        lambda: pools.create_reservation(db, pool, payload.mac, payload.ip, payload.hostname)
    )
    record_audit_event(
        db,
        user.username,
        "dhcp.reservation.create",
        "succeeded",
        detail=f"{reservation.mac} -> {reservation.ip} in pool '{pool.name}'",
    )
    db.commit()
    return reservation


@router.delete("/reservations/{reservation_id}", status_code=204)
def delete_reservation(
    reservation_id: int, user: User = Depends(current_user), db: Session = Depends(get_session)
) -> Response:
    reservation = db.get(DhcpReservation, reservation_id)
    if reservation is None:
        raise HTTPException(status_code=404, detail="Reservation not found. Refresh the list.")
    record_audit_event(
        db,
        user.username,
        "dhcp.reservation.delete",
        "succeeded",
        detail=f"{reservation.mac} -> {reservation.ip}",
    )
    db.delete(reservation)
    db.commit()
    return Response(status_code=204)


# --- leases (R6.4) -------------------------------------------------------------------------------


@router.get("/leases", response_model=list[LeaseRead])
def list_leases(pool_id: int | None = None, db: Session = Depends(get_session)):
    """Active (unexpired) leases, offered or bound, ordered by address."""
    statement = select(DhcpLease)
    if pool_id is not None:
        statement = statement.where(DhcpLease.pool_id == pool_id)
    leases = [lease for lease in db.scalars(statement) if _active(lease)]
    leases.sort(key=lambda lease: tuple(int(part) for part in lease.ip.split(".")))
    return [_lease_read(lease) for lease in leases]


@router.delete("/leases/{lease_id}", status_code=204)
def release_lease(
    lease_id: int, user: User = Depends(current_user), db: Session = Depends(get_session)
) -> Response:
    """Admin release: the address returns to the pool immediately (R6.6, checkpoint C)."""
    lease = db.get(DhcpLease, lease_id)
    if lease is None or not _active(lease):
        raise HTTPException(
            status_code=404, detail="Lease not found or already expired. Refresh the lease list."
        )
    record_audit_event(
        db,
        user.username,
        "dhcp.lease.release",
        "succeeded",
        detail=f"Released {lease.ip} from {lease.mac}",
    )
    db.delete(lease)
    db.commit()
    return Response(status_code=204)
