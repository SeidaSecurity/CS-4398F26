"""DHCP pool and reservation rules (R6.2, R6.3): validation, normalization, conflicts.

Routes stay thin: they call these functions and map the two error types to 422 / 409.
"""

import ipaddress
import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dns.zones import DnsValidationError, normalize_name
from app.models import DhcpLease, DhcpPool, DhcpReservation, utc_now

MIN_LEASE, MAX_LEASE = 60, 604_800  # 1 minute (lab demos) .. 1 week
MAX_DNS_SERVERS = 3
_MAC_HEX = re.compile(r"^[0-9a-f]{12}$")


class DhcpValidationError(ValueError):
    """Input breaks a syntax or range rule (HTTP 422); the message says how to fix it."""


class DhcpConflictError(ValueError):
    """Input clashes with existing data: overlap, duplicate, address in use (HTTP 409)."""


# --- primitives ----------------------------------------------------------------------------------


def normalize_mac(raw: str) -> str:
    """Accept aa:bb:.., aa-bb-.., aabb.ccdd.eeff (Cisco) or 12 hex digits.

    Returns the lowercase colon form aa:bb:cc:dd:ee:ff.
    """
    digits = re.sub(r"[:\-.]", "", raw.strip().lower())
    if not _MAC_HEX.fullmatch(digits) or digits in ("000000000000", "ffffffffffff"):
        raise DhcpValidationError(
            f"MAC address '{raw}' is invalid. Use a form like aa:bb:cc:dd:ee:ff."
        )
    return ":".join(digits[i : i + 2] for i in range(0, 12, 2))


def _ipv4(raw: str, what: str) -> ipaddress.IPv4Address:
    try:
        return ipaddress.IPv4Address(raw.strip())
    except ValueError as exc:
        raise DhcpValidationError(f"{what} must be an IPv4 address like 192.168.50.10.") from exc


def _subnet(raw: str) -> ipaddress.IPv4Network:
    try:
        network = ipaddress.IPv4Network(raw.strip(), strict=True)
    except ValueError as exc:
        raise DhcpValidationError(
            f"The subnet '{raw}' is invalid. Use network/prefix with the host bits zero, e.g. "
            "192.168.50.0/24."
        ) from exc
    if network.prefixlen > 30:
        raise DhcpValidationError("The subnet is too small for clients; use a /30 or larger.")
    return network


def _host_in(network: ipaddress.IPv4Network, address: ipaddress.IPv4Address, what: str) -> None:
    if address == network.network_address:
        raise DhcpValidationError(f"{what} {address} is the network address of {network}.")
    if address == network.broadcast_address:
        raise DhcpValidationError(f"{what} {address} is the broadcast address of {network}.")
    if address not in network:
        raise DhcpValidationError(f"{what} {address} must be inside the subnet {network}.")


def network_of(pool: DhcpPool) -> ipaddress.IPv4Network:
    return ipaddress.IPv4Network(pool.subnet)


def dns_list(pool: DhcpPool) -> list[str]:
    return [item for item in pool.dns_servers.split(",") if item]


# --- pools ---------------------------------------------------------------------------------------


def _validated(fields: dict[str, Any]) -> dict[str, Any]:
    """Check a complete pool definition and return it normalized."""
    name = str(fields["name"]).strip()
    if not 1 <= len(name) <= 64:
        raise DhcpValidationError("Pool name must be 1-64 characters.")
    network = _subnet(fields["subnet"])
    start = _ipv4(fields["range_start"], "Range start")
    end = _ipv4(fields["range_end"], "Range end")
    _host_in(network, start, "Range start")
    _host_in(network, end, "Range end")
    if start > end:
        raise DhcpValidationError("Range start must come before range end.")
    gateway = _ipv4(fields["gateway"], "The gateway")
    _host_in(network, gateway, "The gateway")
    if start <= gateway <= end:
        raise DhcpValidationError(
            f"The gateway {gateway} is inside the dynamic range {start}-{end}; it would be "
            "handed to a client. Move the range or the gateway."
        )
    servers = list(fields["dns_servers"])
    if not 1 <= len(servers) <= MAX_DNS_SERVERS:
        raise DhcpValidationError(f"Give 1-{MAX_DNS_SERVERS} DNS servers (IPv4 addresses).")
    dns = [str(_ipv4(server, "Each DNS server")) for server in servers]
    try:
        domain = normalize_name(str(fields["domain"]), "Domain")
    except DnsValidationError as exc:
        raise DhcpValidationError(str(exc)) from exc
    lease = int(fields["lease_seconds"])
    if not MIN_LEASE <= lease <= MAX_LEASE:
        raise DhcpValidationError(f"Lease time must be {MIN_LEASE}-{MAX_LEASE} seconds.")
    return {
        "name": name,
        "subnet": str(network),
        "range_start": str(start),
        "range_end": str(end),
        "gateway": str(gateway),
        "dns_servers": ",".join(dns),
        "domain": domain,
        "lease_seconds": lease,
    }


def _check_pool_conflicts(db: Session, values: dict[str, Any], exclude_id: int | None) -> None:
    network = ipaddress.IPv4Network(values["subnet"])
    for other in db.scalars(select(DhcpPool)):
        if other.id == exclude_id:
            continue
        if other.name.lower() == values["name"].lower():
            raise DhcpConflictError(f"A pool with the name '{values['name']}' already exists.")
        if network.overlaps(network_of(other)):
            raise DhcpConflictError(
                f"Subnet {network} overlaps pool '{other.name}' ({other.subnet}). "
                "Pools must not overlap."
            )


def create_pool(
    db: Session,
    name: str,
    subnet: str,
    range_start: str,
    range_end: str,
    gateway: str,
    dns_servers: list[str],
    domain: str,
    lease_seconds: int = 86_400,
) -> DhcpPool:
    values = _validated(locals())
    _check_pool_conflicts(db, values, exclude_id=None)
    pool = DhcpPool(**values)
    db.add(pool)
    db.flush()
    return pool


def update_pool(db: Session, pool: DhcpPool, **changes: Any) -> DhcpPool:
    """Apply changes and re-validate the whole pool; reservations must still fit."""
    current = {
        "name": pool.name,
        "subnet": pool.subnet,
        "range_start": pool.range_start,
        "range_end": pool.range_end,
        "gateway": pool.gateway,
        "dns_servers": dns_list(pool),
        "domain": pool.domain,
        "lease_seconds": pool.lease_seconds,
    }
    values = _validated({**current, **{k: v for k, v in changes.items() if v is not None}})
    _check_pool_conflicts(db, values, exclude_id=pool.id)
    network = ipaddress.IPv4Network(values["subnet"])
    for reservation in pool.reservations:
        address = ipaddress.IPv4Address(reservation.ip)
        if address not in network or address in (
            network.network_address,
            network.broadcast_address,
        ):
            raise DhcpConflictError(
                f"The reservation for {reservation.mac} ({reservation.ip}) would fall outside "
                f"{network}. Delete or change that reservation first."
            )
    for key, value in values.items():
        setattr(pool, key, value)
    pool.updated_at = utc_now()
    db.flush()
    return pool


# --- reservations (R6.3) -------------------------------------------------------------------------


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def create_reservation(
    db: Session, pool: DhcpPool, mac: str, ip: str, hostname: str | None = None
) -> DhcpReservation:
    normalized_mac = normalize_mac(mac)
    address = _ipv4(ip, "The reserved address")
    network = network_of(pool)
    _host_in(network, address, "The reserved address")
    if str(address) == pool.gateway:
        raise DhcpValidationError(f"{address} is the pool's gateway and cannot be reserved.")
    name = None
    if hostname:
        try:
            name = normalize_name(hostname, "Hostname")
        except DnsValidationError as exc:
            raise DhcpValidationError(str(exc)) from exc
    for other in pool.reservations:
        if other.mac == normalized_mac:
            raise DhcpConflictError(f"MAC {normalized_mac} already has a reservation ({other.ip}).")
        if other.ip == str(address):
            raise DhcpConflictError(f"The address {address} is already reserved for {other.mac}.")
    lease = db.scalar(select(DhcpLease).where(DhcpLease.ip == str(address)))
    if (
        lease is not None
        and lease.mac != normalized_mac
        and _as_utc(lease.expires_at) > datetime.now(UTC)
    ):
        raise DhcpConflictError(
            f"{address} is currently leased to {lease.mac}. Wait for the lease to end or "
            "choose another address."
        )
    reservation = DhcpReservation(
        pool_id=pool.id, mac=normalized_mac, ip=str(address), hostname=name
    )
    db.add(reservation)
    pool.reservations.append(reservation)
    db.flush()
    return reservation
