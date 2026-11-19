"""Authoritative resolver (R5.1, R5.3): answers from operator-defined zones, no sockets here.

`answer()` is pure: zone data in, DNS reply out, so it is tested with real query packets
(tests/test_dns_resolver.py). `DatabaseResolver` adapts it to dnslib's server and reads the
zones fresh on every query (ADR-0006, design point 1).
"""

from collections.abc import Callable
from dataclasses import dataclass

from dnslib import AAAA, CNAME, PTR, QTYPE, RCODE, RR, SOA, A, DNSRecord
from dnslib.server import BaseResolver
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import DnsZone

NEGATIVE_TTL = 300  # SOA minimum: how long resolvers may cache "no such name" (RFC 2308)
MAX_CNAME_CHAIN = 8
_RDATA = {"A": A, "AAAA": AAAA, "CNAME": CNAME, "PTR": PTR}


@dataclass(frozen=True)
class RecordData:
    fqdn: str  # lowercase, no trailing dot
    rtype: str
    value: str
    ttl: int


@dataclass(frozen=True)
class ZoneData:
    name: str
    serial: int
    records: tuple[RecordData, ...]

    def contains(self, name: str) -> bool:
        return name == self.name or name.endswith("." + self.name)

    def at(self, name: str) -> list[RecordData]:
        return [r for r in self.records if r.fqdn == name]

    def name_exists(self, name: str) -> bool:
        """True for the apex, a name with records, or an empty non-terminal (RFC 8020)."""
        return name == self.name or any(
            r.fqdn == name or r.fqdn.endswith("." + name) for r in self.records
        )

    def soa(self) -> RR:
        return RR(
            self.name,
            QTYPE.SOA,
            ttl=NEGATIVE_TTL,
            rdata=SOA(
                f"ns.{self.name}",
                f"hostmaster.{self.name}",
                (self.serial, 3600, 600, 604_800, NEGATIVE_TTL),
            ),
        )


def load_zones(db: Session) -> list[ZoneData]:
    zones = db.scalars(select(DnsZone).options(selectinload(DnsZone.records)))
    return [
        ZoneData(
            name=zone.name,
            serial=zone.serial,
            records=tuple(
                RecordData(
                    fqdn=zone.name if r.name == "@" else f"{r.name}.{zone.name}",
                    rtype=r.rtype,
                    value=r.value,
                    ttl=r.ttl if r.ttl is not None else zone.default_ttl,
                )
                for r in zone.records
            ),
        )
        for zone in zones
    ]


def _zone_for(name: str, zones: list[ZoneData]) -> ZoneData | None:
    """The most specific local zone containing the name (longest suffix match)."""
    matches = [zone for zone in zones if zone.contains(name)]
    return max(matches, key=lambda zone: len(zone.name)) if matches else None


def _rr(owner: str, record: RecordData) -> RR:
    rdata = _RDATA[record.rtype](record.value)
    return RR(owner, getattr(QTYPE, record.rtype), ttl=record.ttl, rdata=rdata)


def answer(request: DNSRecord, zones: list[ZoneData]) -> DNSRecord:
    reply = request.reply(ra=0, aa=1)  # authoritative only: recursion not available
    question = request.q
    owner = str(question.qname)  # echo the client's spelling in the first answer
    name = owner.lower().rstrip(".")
    qtype = QTYPE.get(question.qtype, str(question.qtype))

    zone = _zone_for(name, zones)
    if zone is None:
        reply.header.aa = 0
        reply.header.rcode = RCODE.REFUSED  # not ours; forwarding is R5.4 (later)
        return reply

    for _ in range(MAX_CNAME_CHAIN):
        if qtype == "SOA" and name == zone.name:
            reply.add_answer(zone.soa())
            return reply
        records = zone.at(name)
        cnames = [r for r in records if r.rtype == "CNAME"]
        if cnames and qtype != "CNAME":
            reply.add_answer(_rr(owner, cnames[0]))
            target = cnames[0].value
            next_zone = _zone_for(target, zones)
            if next_zone is None:
                return reply  # target is outside our zones: the client resolves it
            zone, name, owner = next_zone, target, target
            continue
        matches = [r for r in records if r.rtype == qtype]
        if matches:
            for record in matches:
                reply.add_answer(_rr(owner, record))
            return reply
        reply.header.rcode = RCODE.NOERROR if zone.name_exists(name) else RCODE.NXDOMAIN
        reply.add_auth(zone.soa())
        return reply

    reply.header.rcode = RCODE.SERVFAIL  # CNAME chain too long or looping
    return reply


class DatabaseResolver(BaseResolver):
    """dnslib resolver that answers from the database (fresh read per query)."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self.session_factory = session_factory

    def resolve(self, request: DNSRecord, handler: object) -> DNSRecord:
        with self.session_factory() as db:
            return answer(request, load_zones(db))
