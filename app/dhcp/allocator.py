"""DHCP lease allocator (R6.1, R6.3, R6.6, R6.7; RFC 2131 §4.3). Statechart §7. No sockets.

`Allocator.handle()` takes one parsed client message and returns the reply to send, or None for
silence. Each call is one database transaction. Address uniqueness is enforced by the database
(unique IP on dhcp_leases): if another writer claims an address first, the claim fails, is rolled
back, and the next address is tried (checkpoint C).
"""

import ipaddress
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.dhcp.packet import (
    BOOTREPLY,
    BOOTREQUEST,
    BROADCAST_FLAG,
    DhcpMessage,
    MessageType,
    encode_ip,
    encode_ips,
    encode_u32,
)
from app.dhcp.pools import dns_list, network_of
from app.models import DhcpLease, DhcpPool, DhcpReservation, LogRecord

log = logging.getLogger(__name__)
OFFER_HOLD = timedelta(seconds=60)
EXHAUSTION_LOG_INTERVAL = timedelta(seconds=60)
LOG_SOURCE = "netmgr-dhcp"
_ZERO = ipaddress.IPv4Address("0.0.0.0")


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


class Allocator:
    def __init__(
        self,
        db: Session,
        server_ip: str | ipaddress.IPv4Address,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.db = db
        self.server_ip = ipaddress.IPv4Address(server_ip)
        self.now = now or (lambda: datetime.now(UTC))

    # --- entry points ----------------------------------------------------------------------------

    def handle(self, request: DhcpMessage) -> DhcpMessage | None:
        if request.op != BOOTREQUEST or request.message_type is None:
            return None
        pool = self._pool_for(request)
        if pool is None:
            return None  # never answer for a network we have no pool for (checkpoint B)
        kind = request.message_type
        reply: DhcpMessage | None = None
        if kind is MessageType.DISCOVER:
            reply = self._discover(pool, request)
        elif kind is MessageType.REQUEST:
            reply = self._request(pool, request)
        elif kind is MessageType.RELEASE:
            self._release(pool, request)
        else:
            log.info("Ignoring DHCP %s from %s (not supported)", kind.name, request.mac)
        self.db.commit()
        return reply

    def sweep(self) -> int:
        """Delete expired leases so their addresses return to the pool (R6.6)."""
        expired = [lease for lease in self.db.scalars(select(DhcpLease)) if not self._active(lease)]
        for lease in expired:
            self.db.delete(lease)
        self.db.commit()
        return len(expired)

    # --- lookups ---------------------------------------------------------------------------------

    def _pool_for(self, request: DhcpMessage) -> DhcpPool | None:
        key = request.giaddr if request.giaddr != _ZERO else self.server_ip
        for pool in self.db.scalars(select(DhcpPool)):
            if key in network_of(pool):
                return pool
        return None

    def _active(self, lease: DhcpLease) -> bool:
        return _as_utc(lease.expires_at) > self.now()

    def _lease_of(self, pool: DhcpPool, mac: str) -> DhcpLease | None:
        return self.db.scalar(
            select(DhcpLease).where(DhcpLease.pool_id == pool.id, DhcpLease.mac == mac)
        )

    def _reservation_of(self, pool: DhcpPool, mac: str) -> DhcpReservation | None:
        return self.db.scalar(
            select(DhcpReservation).where(
                DhcpReservation.pool_id == pool.id, DhcpReservation.mac == mac
            )
        )

    def _taken(self, pool: DhcpPool) -> set[str]:
        """Addresses held by an unexpired lease (overridden in tests to simulate a stale view)."""
        return {lease.ip for lease in self.db.scalars(select(DhcpLease)) if self._active(lease)}

    def _reserved(self, pool: DhcpPool) -> dict[str, str]:
        rows = self.db.scalars(select(DhcpReservation).where(DhcpReservation.pool_id == pool.id))
        return {r.ip: r.mac for r in rows}

    # --- DISCOVER --------------------------------------------------------------------------------

    def _discover(self, pool: DhcpPool, request: DhcpMessage) -> DhcpMessage | None:
        mac = request.mac
        lease = self._lease_of(pool, mac)
        reservation = self._reservation_of(pool, mac)
        own = {lease.ip} if lease else set()
        taken, reserved = self._taken(pool), self._reserved(pool)
        start = int(ipaddress.IPv4Address(pool.range_start))
        end = int(ipaddress.IPv4Address(pool.range_end))
        candidates: list[str] = []
        if reservation:  # 1. this MAC's reservation
            candidates.append(reservation.ip)
        if lease:  # 2. this MAC's existing lease
            candidates.append(lease.ip)
        for number in range(start, end + 1):  # 3. lowest free address
            address = str(ipaddress.IPv4Address(number))
            if reserved.get(address, mac) == mac:
                candidates.append(address)
        hostname = request.hostname or (reservation.hostname if reservation else None)
        for address in dict.fromkeys(candidates):
            if address in taken and address not in own:
                continue
            claimed = self._claim(pool, mac, address, hostname)
            if claimed is not None:
                return self._reply(MessageType.OFFER, request, pool, claimed)
        self._log_exhaustion(pool, mac)
        return None

    def _claim(
        self, pool: DhcpPool, mac: str, address: str, hostname: str | None
    ) -> DhcpLease | None:
        """Hold `address` for `mac` as an offer. None if the database says it's already taken."""
        now = self.now()
        try:
            holder = self.db.scalar(select(DhcpLease).where(DhcpLease.ip == address))
            if holder is not None and holder.mac != mac and not self._active(holder):
                self.db.delete(holder)  # someone else's expired lease: reuse the address
                self.db.flush()
            lease = self._lease_of(pool, mac)
            if lease is None:
                lease = DhcpLease(
                    pool_id=pool.id,
                    mac=mac,
                    ip=address,
                    state="offered",
                    expires_at=now + OFFER_HOLD,
                )
                self.db.add(lease)
            else:
                lease.ip = address
                if not (lease.state == "bound" and self._active(lease)):
                    lease.state, lease.expires_at = "offered", now + OFFER_HOLD
            if hostname:
                lease.hostname = hostname[:253]
            lease.updated_at = now
            self.db.flush()
            return lease
        except IntegrityError:
            self.db.rollback()  # another writer got there first; try the next address
            return None

    # --- REQUEST (RFC 2131 §4.3.2) ---------------------------------------------------------------

    def _request(self, pool: DhcpPool, request: DhcpMessage) -> DhcpMessage | None:
        mac, requested = request.mac, request.requested_ip
        lease = self._lease_of(pool, mac)

        if request.server_id is not None:  # SELECTING: the client answers an offer
            if request.server_id != self.server_ip:
                if lease is not None and lease.state == "offered":
                    self.db.delete(lease)  # it chose another server: free our offer
                return None
            if lease is not None and requested is not None and lease.ip == str(requested):
                return self._bind(pool, lease, request)
            return self._reply(MessageType.NAK, request, pool)

        if requested is not None and request.ciaddr == _ZERO:  # INIT-REBOOT
            if requested not in network_of(pool):
                return self._reply(MessageType.NAK, request, pool)  # client moved networks
            if lease is not None and lease.ip == str(requested):
                return self._bind(pool, lease, request)
            reservation = self._reservation_of(pool, mac)
            if reservation is not None and reservation.ip == str(requested):
                claimed = self._claim(pool, mac, reservation.ip, reservation.hostname)
                if claimed is not None:
                    return self._bind(pool, claimed, request)
            holder = self.db.scalar(select(DhcpLease).where(DhcpLease.ip == str(requested)))
            someone_else = holder is not None and holder.mac != mac and self._active(holder)
            if someone_else or lease is not None or reservation is not None:
                return self._reply(MessageType.NAK, request, pool)
            return None  # no record of this client: remain silent

        if request.ciaddr != _ZERO:  # RENEWING / REBINDING
            if (
                lease is not None
                and lease.ip == str(request.ciaddr)
                and lease.state == "bound"
                and self._active(lease)
            ):
                return self._bind(pool, lease, request)
            return self._reply(MessageType.NAK, request, pool)
        return None

    def _bind(self, pool: DhcpPool, lease: DhcpLease, request: DhcpMessage) -> DhcpMessage:
        now = self.now()
        lease.state = "bound"
        lease.expires_at = now + timedelta(seconds=pool.lease_seconds)
        if request.hostname:
            lease.hostname = request.hostname[:253]
        lease.updated_at = now
        self.db.flush()
        return self._reply(MessageType.ACK, request, pool, lease)

    # --- RELEASE ---------------------------------------------------------------------------------

    def _release(self, pool: DhcpPool, request: DhcpMessage) -> None:
        if request.server_id is not None and request.server_id != self.server_ip:
            return
        lease = self._lease_of(pool, request.mac)
        if lease is not None and lease.ip == str(request.ciaddr):
            self.db.delete(lease)

    # --- exhaustion (R6.7) -----------------------------------------------------------------------

    def _log_exhaustion(self, pool: DhcpPool, mac: str) -> None:
        now = self.now()
        prefix = f"DHCP pool '{pool.name}' exhausted"
        recent = [
            record
            for record in self.db.scalars(select(LogRecord).where(LogRecord.source == LOG_SOURCE))
            if record.body.startswith(prefix)
            and _as_utc(record.timestamp) > now - EXHAUSTION_LOG_INTERVAL
        ]
        if recent:
            return  # at most one entry per pool per minute
        body = (
            f"{prefix}: no address available for {mac} in {pool.subnet}. "
            "Widen the range or shorten the lease time."
        )
        self.db.add(
            LogRecord(
                timestamp=now,
                received_at=now,
                source=LOG_SOURCE,
                facility=3,
                severity=4,
                body=body,
                raw_message=body,
                parsed=True,
            )
        )
        log.warning(body)

    # --- replies ---------------------------------------------------------------------------------

    def _reply(
        self,
        kind: MessageType,
        request: DhcpMessage,
        pool: DhcpPool,
        lease: DhcpLease | None = None,
    ) -> DhcpMessage:
        options = {53: bytes([kind]), 54: encode_ip(self.server_ip)}
        if kind is not MessageType.NAK:
            options.update(
                {
                    51: encode_u32(pool.lease_seconds),
                    1: encode_ip(network_of(pool).netmask),
                    3: encode_ip(pool.gateway),
                    6: encode_ips(dns_list(pool)),
                    15: pool.domain.encode(),
                }
            )
        nak = kind is MessageType.NAK
        return DhcpMessage(
            op=BOOTREPLY,
            xid=request.xid,
            chaddr=request.chaddr,
            htype=request.htype,
            hlen=request.hlen,
            flags=request.flags | (BROADCAST_FLAG if nak else 0),
            ciaddr=request.ciaddr if kind is MessageType.ACK else _ZERO,
            yiaddr=ipaddress.IPv4Address(lease.ip) if lease is not None and not nak else _ZERO,
            siaddr=_ZERO if nak else self.server_ip,
            giaddr=request.giaddr,
            options=options,
        )
