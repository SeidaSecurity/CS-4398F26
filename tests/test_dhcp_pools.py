"""DHCP pool and reservation rules (R6.2, R6.3): subnet/range/gateway/DNS/domain/lease bounds."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.dhcp import pools
from app.models import DhcpLease


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as session:
        yield session
    engine.dispose()


GOOD = dict(
    name="lab-clients",
    subnet="192.168.50.0/24",
    range_start="192.168.50.100",
    range_end="192.168.50.199",
    gateway="192.168.50.1",
    dns_servers=["192.168.50.1"],
    domain="lab.local",
    lease_seconds=3600,
)


def make(db, **changes):
    return pools.create_pool(db, **{**GOOD, **changes})


@pytest.fixture
def pool(db):
    return make(db)


# --- R6.2: pool definition -----------------------------------------------------------------------


def test_r6_2_valid_pool_is_stored_normalized(db):
    pool = make(
        db, subnet="192.168.50.0/24", domain="Lab.Local.", dns_servers=["192.168.50.1", "8.8.8.8"]
    )
    assert (pool.subnet, pool.domain) == ("192.168.50.0/24", "lab.local")
    assert pools.dns_list(pool) == ["192.168.50.1", "8.8.8.8"]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"subnet": "192.168.50.1/24"}, "subnet"),  # host bits set
        ({"subnet": "not-a-subnet"}, "subnet"),
        ({"subnet": "192.168.50.0/31"}, "subnet"),  # too small for hosts
        ({"range_start": "192.168.50.0"}, "network"),  # network address: boundary
        ({"range_end": "192.168.50.255"}, "broadcast"),  # broadcast address: boundary
        ({"range_start": "192.168.51.10"}, "inside"),  # outside the subnet
        ({"range_start": "192.168.50.200", "range_end": "192.168.50.100"}, "before"),
        ({"gateway": "10.0.0.1"}, "gateway"),
        ({"gateway": "192.168.50.150"}, "gateway"),  # inside the dynamic range
        ({"dns_servers": []}, "DNS"),
        ({"dns_servers": ["1.1.1.1", "8.8.8.8", "9.9.9.9", "8.8.4.4"]}, "DNS"),  # max 3
        ({"dns_servers": ["dns.example"]}, "DNS"),
        ({"domain": "bad_domain"}, "Domain"),
        ({"name": ""}, "name"),
    ],
)
def test_r6_2_invalid_pools_are_rejected_with_guidance(db, changes, message):
    with pytest.raises(pools.DhcpValidationError, match=message):
        make(db, **changes)


def test_r6_2_first_and_last_usable_hosts_are_allowed(db):
    pool = make(db, range_start="192.168.50.2", range_end="192.168.50.254", gateway="192.168.50.1")
    assert (pool.range_start, pool.range_end) == ("192.168.50.2", "192.168.50.254")


@pytest.mark.parametrize(
    ("seconds", "ok"), [(59, False), (60, True), (604800, True), (604801, False)]
)
def test_r6_2_lease_time_bounds(db, seconds, ok):
    if ok:
        assert make(db, lease_seconds=seconds).lease_seconds == seconds
    else:
        with pytest.raises(pools.DhcpValidationError, match="Lease"):
            make(db, lease_seconds=seconds)


def test_r6_2_overlapping_pools_and_duplicate_names_conflict(db, pool):
    with pytest.raises(pools.DhcpConflictError, match="overlaps"):
        make(
            db,
            name="other",
            subnet="192.168.50.128/25",
            range_start="192.168.50.200",
            range_end="192.168.50.210",
            gateway="192.168.50.129",
        )
    with pytest.raises(pools.DhcpConflictError, match="name"):
        make(
            db,
            subnet="192.168.60.0/24",
            range_start="192.168.60.100",
            range_end="192.168.60.199",
            gateway="192.168.60.1",
        )
    make(
        db,
        name="second",
        subnet="192.168.60.0/24",
        range_start="192.168.60.100",
        range_end="192.168.60.199",
        gateway="192.168.60.1",
    )  # disjoint subnet is fine


def test_r6_2_update_revalidates_the_whole_pool(db, pool):
    pools.update_pool(db, pool, lease_seconds=600, range_end="192.168.50.150")
    assert (pool.lease_seconds, pool.range_end) == (600, "192.168.50.150")
    with pytest.raises(pools.DhcpValidationError, match="gateway"):
        pools.update_pool(db, pool, range_start="192.168.50.1")  # range would cover the gateway


def test_r6_2_update_cannot_strand_a_reservation(db, pool):
    pools.create_reservation(db, pool, "aa:bb:cc:dd:ee:01", "192.168.50.10")
    with pytest.raises(pools.DhcpConflictError, match="reservation"):
        pools.update_pool(
            db,
            pool,
            subnet="192.168.50.128/25",
            range_start="192.168.50.200",
            range_end="192.168.50.210",
            gateway="192.168.50.129",
        )


# --- R6.3: reservations --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "normalized"),
    [
        ("AA:BB:CC:DD:EE:01", "aa:bb:cc:dd:ee:01"),
        ("aa-bb-cc-dd-ee-01", "aa:bb:cc:dd:ee:01"),
        ("aabb.ccdd.ee01", "aa:bb:cc:dd:ee:01"),  # Cisco notation
        ("aabbccddee01", "aa:bb:cc:dd:ee:01"),
    ],
)
def test_r6_3_mac_addresses_are_normalized(raw, normalized):
    assert pools.normalize_mac(raw) == normalized


@pytest.mark.parametrize(
    "raw", ["", "aa:bb:cc:dd:ee", "gg:bb:cc:dd:ee:01", "00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff"]
)
def test_r6_3_bad_mac_addresses_are_rejected(raw):
    with pytest.raises(pools.DhcpValidationError, match="MAC"):
        pools.normalize_mac(raw)


def test_r6_3_reservation_may_sit_outside_the_dynamic_range(db, pool):
    reservation = pools.create_reservation(
        db, pool, "AA-BB-CC-DD-EE-01", "192.168.50.10", "printer"
    )
    assert (reservation.mac, reservation.ip, reservation.hostname) == (
        "aa:bb:cc:dd:ee:01",
        "192.168.50.10",
        "printer",
    )


@pytest.mark.parametrize(
    ("ip", "message"),
    [
        ("192.168.51.10", "inside"),  # other subnet
        ("192.168.50.0", "network"),
        ("192.168.50.255", "broadcast"),
        ("192.168.50.1", "gateway"),
    ],
)
def test_r6_3_reservation_address_rules(db, pool, ip, message):
    with pytest.raises(pools.DhcpValidationError, match=message):
        pools.create_reservation(db, pool, "aa:bb:cc:dd:ee:01", ip)


def test_r6_3_one_reservation_per_mac_and_per_address(db, pool):
    pools.create_reservation(db, pool, "aa:bb:cc:dd:ee:01", "192.168.50.10")
    with pytest.raises(pools.DhcpConflictError, match="MAC"):
        pools.create_reservation(db, pool, "AA:BB:CC:DD:EE:01", "192.168.50.11")
    with pytest.raises(pools.DhcpConflictError, match="address"):
        pools.create_reservation(db, pool, "aa:bb:cc:dd:ee:02", "192.168.50.10")


def test_r6_3_cannot_reserve_an_address_leased_to_another_device(db, pool):
    db.add(
        DhcpLease(
            pool_id=pool.id,
            mac="aa:bb:cc:dd:ee:99",
            ip="192.168.50.150",
            state="bound",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    db.flush()
    with pytest.raises(pools.DhcpConflictError, match="leased"):
        pools.create_reservation(db, pool, "aa:bb:cc:dd:ee:01", "192.168.50.150")


# --- checkpoint C: the database itself forbids duplicate addresses -----------------------------


def test_r6_1_database_rejects_two_leases_for_one_address(db, pool):
    expires = datetime.now(UTC) + timedelta(hours=1)
    db.add(
        DhcpLease(
            pool_id=pool.id,
            mac="aa:bb:cc:dd:ee:01",
            ip="192.168.50.100",
            state="bound",
            expires_at=expires,
        )
    )
    db.flush()
    db.add(
        DhcpLease(
            pool_id=pool.id,
            mac="aa:bb:cc:dd:ee:02",
            ip="192.168.50.100",
            state="offered",
            expires_at=expires,
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()
