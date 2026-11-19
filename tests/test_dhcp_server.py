"""DHCP UDP server over real sockets (R6.1, R6.5, R6.6; SRS 5.3.1). Checkpoints B, D, G.

Runs on 127.0.0.1 with a pool for 127.0.0.0/24, so the server identifier is a real local
address. Replies go to the test client's port instead of broadcast port 68.
"""

import ipaddress
import logging
import socket
import time
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.dhcp import pools
from app.dhcp.allocator import Allocator
from app.dhcp.packet import (
    BOOTREQUEST,
    BROADCAST_FLAG,
    DhcpMessage,
    MessageType,
    build,
    encode_ip,
    parse,
)
from app.dhcp.server import DhcpService, start_dhcp_service
from app.main import app
from app.models import DhcpLease

LOCAL = "127.0.0.1"
MAC = bytes.fromhex("aabbccddee01")


def add_loopback_pool(factory):
    with factory() as db:
        pools.create_pool(
            db,
            name="loopback",
            subnet="127.0.0.0/24",
            range_start="127.0.0.100",
            range_end="127.0.0.110",
            gateway="127.0.0.254",
            dns_servers=["127.0.0.1"],
            domain="lab.local",
            lease_seconds=600,
        )
        db.commit()


def memory_factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def factory():
    engine, session_factory = memory_factory()
    add_loopback_pool(session_factory)
    yield session_factory
    engine.dispose()


@pytest.fixture
def client_socket():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((LOCAL, 0))
    sock.settimeout(3)
    yield sock
    sock.close()


def message(kind, *, requested=None, server=None, xid=0x1234):
    options = {53: bytes([kind]), 12: b"pc1"}
    if requested:
        options[50] = encode_ip(requested)
    if server:
        options[54] = encode_ip(server)
    return build(
        DhcpMessage(op=BOOTREQUEST, xid=xid, chaddr=MAC, flags=BROADCAST_FLAG, options=options)
    )


def exchange(sock, port, payload):
    sock.sendto(payload, (LOCAL, port))
    data, _ = sock.recvfrom(4096)
    return parse(data)


def start(factory, client_socket, **kw):
    service = DhcpService(
        factory, LOCAL, port=0, reply_host=LOCAL, reply_port=client_socket.getsockname()[1], **kw
    )
    service.start()
    return service


# --- the done-criterion: full DORA over real UDP sockets -----------------------------------------


def test_r6_1_full_dora_over_real_udp(factory, client_socket):
    service = start(factory, client_socket)
    try:
        offer = exchange(client_socket, service.port, message(MessageType.DISCOVER))
        assert offer.message_type is MessageType.OFFER
        assert offer.yiaddr == ipaddress.IPv4Address("127.0.0.100")
        assert offer.server_id == ipaddress.IPv4Address(LOCAL)
        ack = exchange(
            client_socket,
            service.port,
            message(MessageType.REQUEST, requested=str(offer.yiaddr), server=LOCAL),
        )
        assert ack.message_type is MessageType.ACK and ack.yiaddr == offer.yiaddr
    finally:
        service.stop()
    with factory() as db:
        lease = db.scalar(select(DhcpLease))
        assert (lease.mac, lease.ip, lease.state, lease.hostname) == (
            "aa:bb:cc:dd:ee:01",
            "127.0.0.100",
            "bound",
            "pc1",
        )


def test_r6_1_binds_to_the_server_ip_not_all_interfaces(factory, client_socket):
    """Checkpoint G: on a multi-homed PC, 0.0.0.0 would also hear the real network."""
    service = start(factory, client_socket)
    try:
        assert service.bound_address == LOCAL
    finally:
        service.stop()


def test_r6_1_malformed_packets_are_ignored_and_service_continues(factory, client_socket):
    service = start(factory, client_socket)
    try:
        client_socket.sendto(b"definitely not dhcp", (LOCAL, service.port))
        client_socket.settimeout(0.5)
        with pytest.raises(TimeoutError):
            client_socket.recvfrom(4096)
        client_socket.settimeout(3)
        offer = exchange(client_socket, service.port, message(MessageType.DISCOVER))
        assert offer.message_type is MessageType.OFFER
    finally:
        service.stop()


def test_r6_1_stop_releases_the_port(factory, client_socket):
    service = start(factory, client_socket)
    port = service.port
    service.stop()
    assert not any(thread.is_alive() for thread in service.threads)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as again:
        again.bind((LOCAL, port))


def test_r6_6_background_sweep_frees_expired_leases(factory, client_socket):
    with factory() as db:
        pool_id = db.scalar(select(pools.DhcpPool.id))
        db.add(
            DhcpLease(
                pool_id=pool_id,
                mac="aa:bb:cc:dd:ee:09",
                ip="127.0.0.105",
                state="bound",
                expires_at=datetime.now(UTC) - timedelta(seconds=1),
            )
        )
        db.commit()
    service = start(factory, client_socket, sweep_interval=0.1)
    try:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            with factory() as db:
                if db.scalar(select(DhcpLease)) is None:
                    break
            time.sleep(0.05)
        with factory() as db:
            assert db.scalar(select(DhcpLease)) is None
    finally:
        service.stop()


# --- checkpoint B: refuse to start where it could become a rogue DHCP server ---------------------


def test_r6_1_refuses_a_server_ip_that_is_not_on_this_computer(factory, caplog):
    with caplog.at_level(logging.ERROR):
        assert start_dhcp_service(factory, "192.0.2.123", port=0) is None  # TEST-NET, not local
    assert "not an address of this computer" in caplog.text


def test_r6_1_refuses_without_a_pool_for_the_server_subnet(caplog):
    engine, empty = memory_factory()
    try:
        with caplog.at_level(logging.ERROR):
            assert start_dhcp_service(empty, LOCAL, port=0) is None
        assert "pool" in caplog.text and "restart" in caplog.text
    finally:
        engine.dispose()


def test_r6_1_refuses_a_missing_server_ip(factory, caplog):
    with caplog.at_level(logging.ERROR):
        assert start_dhcp_service(factory, "", port=0) is None
    assert "DHCP_SERVER_IP" in caplog.text


def test_5_3_1_port_in_use_is_logged_not_raised(factory, caplog):
    holder = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    holder.bind((LOCAL, 0))
    try:
        with caplog.at_level(logging.ERROR):
            assert start_dhcp_service(factory, LOCAL, port=holder.getsockname()[1]) is None
        assert "could not listen" in caplog.text
    finally:
        holder.close()


# --- lifespan ------------------------------------------------------------------------------------


def test_r6_1_lifespan_starts_and_stops_dhcp(factory, monkeypatch):
    monkeypatch.setattr("app.main.SessionLocal", factory)
    monkeypatch.setenv("DHCP_ENABLED", "true")
    monkeypatch.setenv("DHCP_SERVER_IP", LOCAL)
    monkeypatch.setenv("DHCP_PORT", "0")
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        service = app.state.dhcp_service
        assert service is not None and service.bound_address == LOCAL
    assert not any(thread.is_alive() for thread in service.threads)


def test_5_3_1_app_runs_when_dhcp_refuses_to_start(monkeypatch):
    engine, empty = memory_factory()
    monkeypatch.setattr("app.main.SessionLocal", empty)
    monkeypatch.setenv("DHCP_ENABLED", "true")
    monkeypatch.setenv("DHCP_SERVER_IP", LOCAL)
    monkeypatch.setenv("DHCP_PORT", "0")
    try:
        with TestClient(app) as client:
            assert client.get("/health").status_code == 200
            assert app.state.dhcp_service is None
    finally:
        engine.dispose()


# --- checkpoint D: leases survive a restart (R6.5) ------------------------------------------------


def test_r6_5_leases_survive_a_restart(tmp_path, client_socket):
    url = f"sqlite:///{tmp_path / 'leases.db'}"
    engine = create_engine(url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    first = sessionmaker(bind=engine, expire_on_commit=False)
    add_loopback_pool(first)
    service = start(first, client_socket)
    try:
        offer = exchange(client_socket, service.port, message(MessageType.DISCOVER))
        exchange(
            client_socket,
            service.port,
            message(MessageType.REQUEST, requested=str(offer.yiaddr), server=LOCAL),
        )
    finally:
        service.stop()
    engine.dispose()  # the "application" is gone

    engine = create_engine(url, connect_args={"check_same_thread": False})
    second = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        with second() as db:
            lease = db.scalar(select(DhcpLease))
            assert (lease.ip, lease.state) == ("127.0.0.100", "bound")
            again = Allocator(db, LOCAL).handle(parse(message(MessageType.DISCOVER, xid=0x99)))
            assert again.yiaddr == ipaddress.IPv4Address("127.0.0.100")  # same client, same address
    finally:
        engine.dispose()
