"""Zone and record rules (R5.2): name syntax, values per type, TTL bounds, CNAME exclusivity."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.dns import zones
from app.models import DnsRecord


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as session:
        yield session
    engine.dispose()


@pytest.fixture
def lab(db):
    return zones.create_zone(db, "lab.local")


# --- names ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Lab.Local", "lab.local"),  # case-insensitive, stored lowercase
        ("lab.local.", "lab.local"),  # trailing dot accepted
        ("198.168.192.in-addr.arpa", "198.168.192.in-addr.arpa"),  # reverse zone
        ("a" * 63 + ".local", "a" * 63 + ".local"),  # 63-character label: boundary
    ],
)
def test_r5_2_zone_names_are_normalized(db, raw, expected):
    assert zones.create_zone(db, raw).name == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "a" * 64 + ".local",  # 64-character label: just over
        ".".join(["a" * 63] * 4),  # 255 characters: over the 253 total
        "-bad.local",
        "bad-.local",
        "under_score.local",
        "two..dots",
    ],
)
def test_r5_2_bad_zone_names_are_rejected(db, raw):
    with pytest.raises(zones.DnsValidationError):
        zones.create_zone(db, raw)


def test_r5_2_total_name_length_boundary(db):
    name_253 = ".".join(["a" * 63, "b" * 63, "c" * 63, "d" * 61])
    assert len(name_253) == 253
    assert zones.create_zone(db, name_253).name == name_253


def test_r5_2_duplicate_zone_is_a_conflict(db, lab):
    with pytest.raises(zones.DnsConflictError):
        zones.create_zone(db, "LAB.local.")


# --- record values -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rtype", "value", "stored"),
    [
        ("A", "192.168.198.11", "192.168.198.11"),
        ("AAAA", "2001:DB8:0:0:0:0:0:1", "2001:db8::1"),  # normalized to compressed form
        ("CNAME", "R1.Lab.Local.", "r1.lab.local"),
        ("PTR", "r1.lab.local", "r1.lab.local"),
    ],
)
def test_r5_2_values_are_validated_and_normalized(db, lab, rtype, value, stored):
    record = zones.create_record(db, lab, "r9" if rtype != "CNAME" else "alias", rtype, value)
    assert record.value == stored


@pytest.mark.parametrize(
    ("rtype", "value"),
    [
        ("A", "192.168.198.256"),
        ("A", "2001:db8::1"),  # IPv6 in an A record
        ("AAAA", "192.168.198.11"),  # IPv4 in an AAAA record
        ("CNAME", "not a hostname"),
        ("PTR", ""),
        ("MX", "mail.lab.local"),  # unsupported type
    ],
)
def test_r5_2_bad_values_are_rejected(db, lab, rtype, value):
    with pytest.raises(zones.DnsValidationError):
        zones.create_record(db, lab, "r1", rtype, value)


@pytest.mark.parametrize(("ttl", "ok"), [(29, False), (30, True), (604800, True), (604801, False)])
def test_r5_2_ttl_bounds(db, lab, ttl, ok):
    if ok:
        assert zones.create_record(db, lab, "r1", "A", "192.168.198.11", ttl=ttl).ttl == ttl
    else:
        with pytest.raises(zones.DnsValidationError):
            zones.create_record(db, lab, "r1", "A", "192.168.198.11", ttl=ttl)


@pytest.mark.parametrize(("name", "stored"), [("@", "@"), ("R1", "r1"), ("a.b", "a.b")])
def test_r5_2_record_names_are_relative_and_lowercase(db, lab, name, stored):
    assert zones.create_record(db, lab, name, "A", "192.168.198.11").name == stored


# --- CNAME exclusivity (RFC 1034 §3.6.2) and duplicates ------------------------------------------


def test_r5_2_cname_cannot_join_an_existing_name(db, lab):
    zones.create_record(db, lab, "r1", "A", "192.168.198.11")
    with pytest.raises(zones.DnsConflictError, match="CNAME"):
        zones.create_record(db, lab, "r1", "CNAME", "r2.lab.local")


def test_r5_2_nothing_can_join_a_cname(db, lab):
    zones.create_record(db, lab, "www", "CNAME", "r1.lab.local")
    with pytest.raises(zones.DnsConflictError, match="CNAME"):
        zones.create_record(db, lab, "WWW", "A", "192.168.198.11")


def test_r5_2_no_cname_at_the_zone_apex(db, lab):
    with pytest.raises(zones.DnsValidationError, match="apex"):
        zones.create_record(db, lab, "@", "CNAME", "r1.lab.local")


def test_r5_2_exact_duplicate_record_is_a_conflict(db, lab):
    zones.create_record(db, lab, "r1", "A", "192.168.198.11")
    with pytest.raises(zones.DnsConflictError):
        zones.create_record(db, lab, "r1", "A", "192.168.198.11")
    zones.create_record(db, lab, "r1", "A", "192.168.198.12")  # a second address is fine


def test_r5_2_changes_bump_the_zone_serial(db, lab):
    start = lab.serial
    record = zones.create_record(db, lab, "r1", "A", "192.168.198.11")
    zones.update_record(db, record, value="192.168.198.21")
    zones.delete_record(db, record)
    assert lab.serial == start + 3
    assert db.query(DnsRecord).count() == 0


def test_r5_2_update_keeps_cname_rule(db, lab):
    zones.create_record(db, lab, "r1", "A", "192.168.198.11")
    alias = zones.create_record(db, lab, "www", "CNAME", "r1.lab.local")
    with pytest.raises(zones.DnsConflictError):
        zones.update_record(db, alias, name="r1")
