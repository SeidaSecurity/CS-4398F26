"""Resolver behavior on real DNS packets (R5.1, R5.3; RFC 1035/2308). Checkpoint A of the DNS plan.

Every test sends a real dnslib query, then round-trips the reply through wire format
(pack -> parse) and checks header flags and sections, exactly as a client would see them.
"""

import pytest
from dnslib import QTYPE, RCODE, DNSRecord
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.dns import zones
from app.dns.resolver import answer, load_zones


@pytest.fixture
def lab_zones():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as db:
        lab = zones.create_zone(db, "lab.local", default_ttl=3600)
        zones.create_record(db, lab, "r1", "A", "192.168.198.11")
        zones.create_record(db, lab, "r1", "AAAA", "2001:db8::11")
        zones.create_record(db, lab, "r2", "A", "192.168.198.12", ttl=60)
        zones.create_record(db, lab, "www", "CNAME", "r1.lab.local")
        zones.create_record(db, lab, "ext", "CNAME", "example.com")
        zones.create_record(db, lab, "dangling", "CNAME", "nothing.lab.local")
        zones.create_record(db, lab, "loop1", "CNAME", "loop2.lab.local")
        zones.create_record(db, lab, "loop2", "CNAME", "loop1.lab.local")
        zones.create_record(db, lab, "host.deep", "A", "192.168.198.50")
        sub = zones.create_zone(db, "sub.lab.local")
        zones.create_record(db, sub, "r9", "A", "10.9.9.9")
        rev = zones.create_zone(db, "198.168.192.in-addr.arpa")
        zones.create_record(db, rev, "11", "PTR", "r1.lab.local")
        db.commit()
        data = load_zones(db)
    engine.dispose()
    return data


def ask(zone_data, name, qtype="A"):
    query = DNSRecord.question(name, qtype)
    reply = answer(query, zone_data)
    wire = DNSRecord.parse(reply.pack())  # what a real client receives
    assert wire.header.id == query.header.id and wire.header.qr == 1
    return wire


def rdata(rr_list):
    return [(str(rr.rname).rstrip("."), QTYPE[rr.rtype], str(rr.rdata).rstrip("."), rr.ttl)
            for rr in rr_list]


# --- R5.1: authoritative answers -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "qtype", "expected"),
    [
        ("r1.lab.local", "A", [("r1.lab.local", "A", "192.168.198.11", 3600)]),
        ("r1.lab.local", "AAAA", [("r1.lab.local", "AAAA", "2001:db8::11", 3600)]),
        ("r2.lab.local", "A", [("r2.lab.local", "A", "192.168.198.12", 60)]),  # record TTL
        ("R1.LAB.LOCAL.", "A", [("R1.LAB.LOCAL", "A", "192.168.198.11", 3600)]),  # case-insensitive
        ("11.198.168.192.in-addr.arpa", "PTR",
         [("11.198.168.192.in-addr.arpa", "PTR", "r1.lab.local", 3600)]),
    ],
)
def test_r5_1_authoritative_answers(lab_zones, name, qtype, expected):
    reply = ask(lab_zones, name, qtype)
    assert reply.header.aa == 1
    assert reply.header.rcode == RCODE.NOERROR
    assert rdata(reply.rr) == expected


def test_r5_1_cname_is_followed_inside_local_zones(lab_zones):
    reply = ask(lab_zones, "www.lab.local", "A")
    assert reply.header.aa == 1 and reply.header.rcode == RCODE.NOERROR
    assert rdata(reply.rr) == [
        ("www.lab.local", "CNAME", "r1.lab.local", 3600),
        ("r1.lab.local", "A", "192.168.198.11", 3600),
    ]


def test_r5_1_cname_query_returns_only_the_cname(lab_zones):
    assert rdata(ask(lab_zones, "www.lab.local", "CNAME").rr) == [
        ("www.lab.local", "CNAME", "r1.lab.local", 3600)
    ]


def test_r5_1_cname_to_an_outside_name_stops_at_the_cname(lab_zones):
    reply = ask(lab_zones, "ext.lab.local", "A")
    assert reply.header.rcode == RCODE.NOERROR
    assert rdata(reply.rr) == [("ext.lab.local", "CNAME", "example.com", 3600)]


def test_r5_1_cname_loop_is_bounded(lab_zones):
    reply = ask(lab_zones, "loop1.lab.local", "A")  # must terminate, not hang or overflow
    assert reply.header.rcode == RCODE.SERVFAIL
    assert len(reply.rr) <= 8


def test_r5_1_most_specific_zone_wins(lab_zones):
    reply = ask(lab_zones, "r9.sub.lab.local", "A")
    assert rdata(reply.rr) == [("r9.sub.lab.local", "A", "10.9.9.9", 3600)]


def test_r5_1_soa_at_the_apex(lab_zones):
    reply = ask(lab_zones, "lab.local", "SOA")
    assert reply.header.aa == 1
    [soa] = reply.rr
    assert QTYPE[soa.rtype] == "SOA"
    assert str(soa.rdata.mname).rstrip(".") == "ns.lab.local"
    assert soa.rdata.times[0] >= 1  # serial


# --- R5.3: negative answers ----------------------------------------------------------------------


def _assert_negative(reply, rcode, zone_name):
    assert reply.header.aa == 1
    assert reply.header.rcode == rcode
    assert reply.rr == []
    [soa] = reply.auth  # RFC 2308: SOA in the authority section, its TTL = negative TTL
    assert QTYPE[soa.rtype] == "SOA" and str(soa.rname).rstrip(".") == zone_name
    assert soa.ttl == 300


def test_r5_3_missing_name_is_authoritative_nxdomain(lab_zones):
    _assert_negative(ask(lab_zones, "nope.lab.local"), RCODE.NXDOMAIN, "lab.local")


def test_r5_3_missing_reverse_name_is_nxdomain(lab_zones):
    _assert_negative(
        ask(lab_zones, "99.198.168.192.in-addr.arpa", "PTR"),
        RCODE.NXDOMAIN,
        "198.168.192.in-addr.arpa",
    )


@pytest.mark.parametrize(
    ("name", "qtype"),
    [
        ("r2.lab.local", "AAAA"),  # name exists, type doesn't
        ("lab.local", "A"),  # the apex always exists
        ("deep.lab.local", "A"),  # empty non-terminal (host.deep exists), RFC 8020
        ("r1.lab.local", "MX"),  # unsupported type on an existing name
    ],
)
def test_r5_3_existing_name_without_that_type_is_nodata(lab_zones, name, qtype):
    _assert_negative(ask(lab_zones, name, qtype), RCODE.NOERROR, "lab.local")


def test_r5_3_dangling_cname_keeps_the_cname_and_reports_nxdomain(lab_zones):
    reply = ask(lab_zones, "dangling.lab.local", "A")
    assert reply.header.rcode == RCODE.NXDOMAIN
    assert rdata(reply.rr) == [("dangling.lab.local", "CNAME", "nothing.lab.local", 3600)]


def test_r5_3_names_outside_local_zones_are_refused(lab_zones):
    reply = ask(lab_zones, "example.com")
    assert reply.header.rcode == RCODE.REFUSED
    assert reply.header.aa == 0  # we are not authoritative for it
    assert reply.rr == [] and reply.auth == []
