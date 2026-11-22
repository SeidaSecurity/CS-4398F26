"""DHCP allocator state machine (R6.1, R6.3, R6.6, R6.7; RFC 2131 §4.3). Statechart §7.

Clients are simulated with real DhcpMessage objects; a fixed clock makes expiry testable.
Covers checkpoint B (unknown subnet -> silent) and C (racing for an address -> no duplicate).
"""

import ipaddress
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.dhcp import pools
from app.dhcp.allocator import Allocator
from app.dhcp.packet import (
    BOOTREPLY,
    BOOTREQUEST,
    BROADCAST_FLAG,
    DhcpMessage,
    MessageType,
    encode_ip,
)
from app.models import DhcpLease, LogRecord

SERVER = ipaddress.IPv4Address("192.168.50.1")
T0 = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
IP = ipaddress.IPv4Address


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
def pool(db):
    pool = pools.create_pool(
        db,
        name="lab",
        subnet="192.168.50.0/24",
        range_start="192.168.50.100",
        range_end="192.168.50.102",
        gateway="192.168.50.1",
        dns_servers=["192.168.50.1"],
        domain="lab.local",
        lease_seconds=3600,
    )
    db.commit()
    return pool


class Clock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def alloc(db, pool, clock):
    return Allocator(db, SERVER, now=clock)


def mac_bytes(n):
    return bytes.fromhex(f"aabbccddee{n:02x}")


def client(kind, n, *, requested=None, server=None, ciaddr="0.0.0.0", giaddr="0.0.0.0", host=None):
    options = {53: bytes([kind])}
    if requested:
        options[50] = encode_ip(requested)
    if server:
        options[54] = encode_ip(server)
    if host:
        options[12] = host.encode()
    return DhcpMessage(
        op=BOOTREQUEST,
        xid=1000 + n,
        chaddr=mac_bytes(n),
        flags=BROADCAST_FLAG,
        ciaddr=IP(ciaddr),
        giaddr=IP(giaddr),
        options=options,
    )


def discover(alloc, n, **kw):
    return alloc.handle(client(MessageType.DISCOVER, n, **kw))


def select_offer(alloc, n, ip, server=SERVER):
    return alloc.handle(client(MessageType.REQUEST, n, requested=str(ip), server=str(server)))


def lease_for(db, n):
    return db.scalar(select(DhcpLease).where(DhcpLease.mac == f"aa:bb:cc:dd:ee:{n:02x}"))


# --- R6.1: DORA ----------------------------------------------------------------------------------


def test_r6_1_full_dora_exchange(alloc, db, clock):
    offer = discover(alloc, 1, host="pc1")
    assert offer.message_type is MessageType.OFFER
    assert (offer.op, offer.xid, offer.mac) == (BOOTREPLY, 1001, "aa:bb:cc:dd:ee:01")
    assert offer.yiaddr == IP("192.168.50.100") and offer.siaddr == SERVER
    assert offer.server_id == SERVER
    assert offer.options[1] == encode_ip("255.255.255.0")
    assert offer.options[3] == encode_ip("192.168.50.1")
    assert offer.options[6] == encode_ip("192.168.50.1")
    assert offer.options[15] == b"lab.local"
    assert int.from_bytes(offer.options[51], "big") == 3600
    assert lease_for(db, 1).state == "offered"

    ack = select_offer(alloc, 1, offer.yiaddr)
    assert ack.message_type is MessageType.ACK and ack.yiaddr == offer.yiaddr
    lease = lease_for(db, 1)
    assert (lease.state, lease.hostname) == ("bound", "pc1")
    assert lease.expires_at.replace(tzinfo=UTC) == T0 + timedelta(seconds=3600)


def test_r6_1_lowest_free_address_then_next(alloc):
    assert discover(alloc, 1).yiaddr == IP("192.168.50.100")
    assert discover(alloc, 2).yiaddr == IP("192.168.50.101")


def test_r6_1_same_client_gets_same_address_again(alloc):
    first = discover(alloc, 1)
    select_offer(alloc, 1, first.yiaddr)
    again = discover(alloc, 1)  # e.g. the client rebooted
    assert again.yiaddr == first.yiaddr


def test_r6_3_reservation_wins_even_outside_the_range(alloc, db, pool):
    pools.create_reservation(db, pool, "aa:bb:cc:dd:ee:07", "192.168.50.10", "printer")
    db.commit()
    offer = discover(alloc, 7)
    assert offer.yiaddr == IP("192.168.50.10")
    select_offer(alloc, 7, offer.yiaddr)
    assert lease_for(db, 7).hostname == "printer"  # reservation hostname when client sends none


def test_r6_1_reply_echoes_relay_and_flags(alloc, db):
    relay_pool = pools.create_pool(
        db,
        name="remote",
        subnet="10.9.0.0/24",
        range_start="10.9.0.100",
        range_end="10.9.0.110",
        gateway="10.9.0.1",
        dns_servers=["10.9.0.1"],
        domain="remote.lab",
        lease_seconds=600,
    )
    db.commit()
    offer = discover(alloc, 3, giaddr="10.9.0.1")  # relayed from another subnet
    assert offer.giaddr == IP("10.9.0.1") and offer.flags & BROADCAST_FLAG
    assert offer.yiaddr in pools.network_of(relay_pool)


# --- REQUEST variants (RFC 2131 §4.3.2) ---------------------------------------------------------


def test_r6_1_client_choosing_another_server_frees_our_offer(alloc, db):
    offer = discover(alloc, 1)
    assert select_offer(alloc, 1, offer.yiaddr, server="192.168.50.250") is None
    assert lease_for(db, 1) is None
    assert discover(alloc, 2).yiaddr == offer.yiaddr  # address is free again


def test_r6_1_selecting_a_different_address_is_nak(alloc):
    discover(alloc, 1)
    nak = select_offer(alloc, 1, "192.168.50.101")
    assert nak.message_type is MessageType.NAK and nak.yiaddr == IP("0.0.0.0")


def test_r6_1_request_without_an_offer_is_nak(alloc):
    assert select_offer(alloc, 9, "192.168.50.100").message_type is MessageType.NAK


def test_r6_1_init_reboot_cases(alloc, db):
    select_offer(alloc, 1, discover(alloc, 1).yiaddr)
    reboot = alloc.handle(client(MessageType.REQUEST, 1, requested="192.168.50.100"))
    assert reboot.message_type is MessageType.ACK  # known lease
    wrong_net = alloc.handle(client(MessageType.REQUEST, 1, requested="10.1.1.1"))
    assert wrong_net.message_type is MessageType.NAK  # moved to another network
    stranger = alloc.handle(client(MessageType.REQUEST, 5, requested="192.168.50.150"))
    assert stranger is None  # no record of this client: stay silent
    thief = alloc.handle(client(MessageType.REQUEST, 6, requested="192.168.50.100"))
    assert thief.message_type is MessageType.NAK  # address belongs to someone else


def test_r6_1_renewing_extends_and_unknown_renewal_is_nak(alloc, db, clock):
    select_offer(alloc, 1, discover(alloc, 1).yiaddr)
    clock.now = T0 + timedelta(minutes=30)
    renew = alloc.handle(client(MessageType.REQUEST, 1, ciaddr="192.168.50.100"))
    assert renew.message_type is MessageType.ACK and renew.ciaddr == IP("192.168.50.100")
    assert lease_for(db, 1).expires_at.replace(tzinfo=UTC) == clock.now + timedelta(seconds=3600)
    bogus = alloc.handle(client(MessageType.REQUEST, 4, ciaddr="192.168.50.101"))
    assert bogus.message_type is MessageType.NAK


# --- R6.6: release and expiry --------------------------------------------------------------------


def test_r6_6_release_returns_the_address(alloc, db):
    select_offer(alloc, 1, discover(alloc, 1).yiaddr)
    assert (
        alloc.handle(client(MessageType.RELEASE, 1, ciaddr="192.168.50.100", server=str(SERVER)))
        is None
    )
    assert lease_for(db, 1) is None
    assert discover(alloc, 2).yiaddr == IP("192.168.50.100")


def test_r6_6_unclaimed_offer_expires_after_the_hold_time(alloc, clock):
    discover(alloc, 1)
    clock.now = T0 + timedelta(seconds=61)  # offer hold is 60 s
    assert discover(alloc, 2).yiaddr == IP("192.168.50.100")


def test_r6_6_sweep_removes_expired_leases(alloc, db, clock):
    select_offer(alloc, 1, discover(alloc, 1).yiaddr)
    clock.now = T0 + timedelta(seconds=3599)
    assert alloc.sweep() == 0  # boundary: still valid
    clock.now = T0 + timedelta(seconds=3600)
    assert alloc.sweep() == 1
    assert lease_for(db, 1) is None


# --- R6.7: exhaustion ----------------------------------------------------------------------------


def _exhaustion_logs(db):
    return list(db.scalars(select(LogRecord).where(LogRecord.source == "netmgr-dhcp")))


def test_r6_7_exhausted_pool_sends_no_offer_and_logs_once_per_minute(alloc, db, clock):
    for n in (1, 2, 3):
        assert discover(alloc, n) is not None  # fills .100-.102
    assert discover(alloc, 4) is None
    assert discover(alloc, 5) is None
    logs = _exhaustion_logs(db)
    assert len(logs) == 1  # rate-limited
    assert "lab" in logs[0].body and "exhausted" in logs[0].body and logs[0].severity == 4
    clock.now = T0 + timedelta(seconds=59)  # offers held for 60 s, so still exhausted
    assert discover(alloc, 6) is None
    assert len(_exhaustion_logs(db)) == 1
    db.query(DhcpLease).update({DhcpLease.expires_at: T0 + timedelta(hours=1)})  # keep it full
    db.commit()
    clock.now = T0 + timedelta(seconds=61)
    assert discover(alloc, 7) is None
    assert len(_exhaustion_logs(db)) == 2


# --- checkpoint B: never answer for a network we have no pool for --------------------------------


def test_r6_1_no_pool_for_the_server_subnet_means_silence(db, pool, clock):
    stranger = Allocator(db, IP("192.168.1.49"), now=clock)  # e.g. the real home network
    assert stranger.handle(client(MessageType.DISCOVER, 1)) is None
    assert db.scalar(select(DhcpLease)) is None


def test_r6_1_unknown_relay_subnet_is_ignored(alloc, db):
    assert discover(alloc, 1, giaddr="172.16.0.1") is None


def test_r6_1_replies_and_unsupported_types_are_ignored(alloc):
    reply = client(MessageType.DISCOVER, 1)
    reply.op = BOOTREPLY
    assert alloc.handle(reply) is None
    assert alloc.handle(client(MessageType.INFORM, 1)) is None
    assert alloc.handle(client(MessageType.DECLINE, 1, requested="192.168.50.100")) is None


# --- checkpoint C: concurrent allocation cannot duplicate an address ----------------------------


def test_r6_1_racing_for_an_address_never_duplicates_it(db, pool, clock):
    """Another writer commits .100 after we decided it was free; we must move on, not duplicate."""

    class StaleView(Allocator):
        def _taken(self, pool):  # pretend we read before the other server's commit
            return set()

    db.add(
        DhcpLease(
            pool_id=pool.id,
            mac="aa:bb:cc:dd:ee:99",
            ip="192.168.50.100",
            state="bound",
            expires_at=T0 + timedelta(hours=1),
        )
    )
    db.commit()
    offer = StaleView(db, SERVER, now=clock).handle(client(MessageType.DISCOVER, 1))
    assert offer.yiaddr == IP("192.168.50.101")  # IntegrityError on .100 -> retried next
    ips = [lease.ip for lease in db.scalars(select(DhcpLease))]
    assert sorted(ips) == ["192.168.50.100", "192.168.50.101"]
