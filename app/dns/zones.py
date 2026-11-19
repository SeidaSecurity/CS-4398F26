"""Zone and record rules (R5.2): validation, normalization, CNAME exclusivity, SOA serial.

Routes stay thin: they call these functions and map the two error types to 422 / 409.
"""

import ipaddress
import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import DnsRecord, DnsZone, utc_now

RECORD_TYPES = ("A", "AAAA", "CNAME", "PTR")
MIN_TTL, MAX_TTL = 30, 604_800  # 30 s .. 1 week
DEFAULT_TTL = 3600
APEX = "@"
_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")


class DnsValidationError(ValueError):
    """Input breaks a syntax or range rule (HTTP 422); the message says how to fix it."""


class DnsConflictError(ValueError):
    """Input conflicts with existing data, e.g. a duplicate or a CNAME clash (HTTP 409)."""


# --- names and values ----------------------------------------------------------------------------


def normalize_name(raw: str, what: str = "Name") -> str:
    """Lowercase a DNS name, drop a trailing dot, and check RFC 1035 label/length rules."""
    name = raw.strip().lower().removesuffix(".")
    if not name or len(name) > 253:
        raise DnsValidationError(f"{what} must be 1-253 characters, e.g. 'lab.local'.")
    for label in name.split("."):
        if not _LABEL.fullmatch(label):
            raise DnsValidationError(
                f"{what} '{raw}' is invalid: each dot-separated part must be 1-63 letters, "
                "digits or hyphens, and cannot start or end with a hyphen."
            )
    return name


def _record_name(raw: str) -> str:
    raw = raw.strip()
    return APEX if raw == APEX else normalize_name(raw, "Record name")


def _record_value(rtype: str, raw: str) -> str:
    if rtype not in RECORD_TYPES:
        raise DnsValidationError(f"Unsupported record type '{rtype}'. Use A, AAAA, CNAME or PTR.")
    value = raw.strip()
    try:
        if rtype == "A":
            return str(ipaddress.IPv4Address(value))
        if rtype == "AAAA":
            return str(ipaddress.IPv6Address(value))
    except ValueError as exc:
        kind = "an IPv4 address like 192.168.198.11" if rtype == "A" else "an IPv6 address"
        raise DnsValidationError(f"An {rtype} record's value must be {kind}.") from exc
    return normalize_name(value, f"{rtype} target")


def _ttl(ttl: int | None) -> int | None:
    if ttl is not None and not MIN_TTL <= ttl <= MAX_TTL:
        raise DnsValidationError(
            f"TTL must be {MIN_TTL}-{MAX_TTL} seconds, or empty for the zone default."
        )
    return ttl


def _touch(zone: DnsZone) -> None:
    zone.serial = (zone.serial or 0) + 1
    zone.updated_at = utc_now()


# --- zones ---------------------------------------------------------------------------------------


def create_zone(db: Session, name: str, default_ttl: int = DEFAULT_TTL) -> DnsZone:
    normalized = normalize_name(name, "Zone name")
    if _ttl(default_ttl) is None:
        raise DnsValidationError("A zone needs a default TTL.")
    if db.scalar(select(DnsZone).where(DnsZone.name == normalized)) is not None:
        raise DnsConflictError(f"Zone '{normalized}' already exists.")
    zone = DnsZone(name=normalized, default_ttl=default_ttl, serial=1)
    db.add(zone)
    db.flush()
    return zone


def update_zone(db: Session, zone: DnsZone, default_ttl: int) -> DnsZone:
    if _ttl(default_ttl) is None:
        raise DnsValidationError("A zone needs a default TTL.")
    zone.default_ttl = default_ttl
    _touch(zone)
    db.flush()
    return zone


# --- records -------------------------------------------------------------------------------------


def _check_conflicts(
    db: Session, zone: DnsZone, name: str, rtype: str, value: str, exclude_id: int | None
) -> None:
    if rtype == "CNAME" and name == APEX:
        raise DnsValidationError("A CNAME is not allowed at the zone apex ('@'); use an A record.")
    others = [
        record
        for record in db.scalars(
            select(DnsRecord).where(
                DnsRecord.zone_id == zone.id, func.lower(DnsRecord.name) == name
            )
        )
        if record.id != exclude_id
    ]
    if any(r.rtype == rtype and r.value == value for r in others):
        raise DnsConflictError(f"That {rtype} record already exists for '{name}'.")
    if others and (rtype == "CNAME" or any(r.rtype == "CNAME" for r in others)):
        raise DnsConflictError(
            f"'{name}' cannot have a CNAME together with other records (RFC 1034). "
            "Remove the other records or choose a different name."
        )


def create_record(
    db: Session, zone: DnsZone, name: str, rtype: str, value: str, ttl: int | None = None
) -> DnsRecord:
    rtype = rtype.strip().upper()
    normalized_value = _record_value(rtype, value)
    normalized_name = _record_name(name)
    _check_conflicts(db, zone, normalized_name, rtype, normalized_value, exclude_id=None)
    record = DnsRecord(
        zone_id=zone.id, name=normalized_name, rtype=rtype, value=normalized_value, ttl=_ttl(ttl)
    )
    db.add(record)
    _touch(zone)
    db.flush()
    return record


def update_record(
    db: Session,
    record: DnsRecord,
    name: str | None = None,
    value: str | None = None,
    ttl: int | None = None,
    clear_ttl: bool = False,
) -> DnsRecord:
    """Change name, value and/or TTL (the type is fixed: delete and re-add to change it)."""
    new_name = _record_name(name) if name is not None else record.name
    new_value = _record_value(record.rtype, value) if value is not None else record.value
    _check_conflicts(db, record.zone, new_name, record.rtype, new_value, exclude_id=record.id)
    record.name, record.value = new_name, new_value
    if clear_ttl:
        record.ttl = None
    elif ttl is not None:
        record.ttl = _ttl(ttl)
    _touch(record.zone)
    db.flush()
    return record


def delete_record(db: Session, record: DnsRecord) -> None:
    _touch(record.zone)
    db.delete(record)
    db.flush()
