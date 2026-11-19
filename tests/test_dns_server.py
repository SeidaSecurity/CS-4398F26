"""UDP/TCP DNS server lifecycle and subsystem robustness (R5.1, SRS 5.3.1). Checkpoints B and D."""

import logging
import socket

import pytest
from dnslib import RCODE, DNSRecord
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.dns import zones
from app.dns.server import DnsService, start_dns_service
from app.main import app


@pytest.fixture
def factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as db:
        lab = zones.create_zone(db, "lab.local")
        zones.create_record(db, lab, "r1", "A", "192.168.198.11")
        db.commit()
    yield session_factory
    engine.dispose()


@pytest.fixture
def occupied_udp_port():
    """A UDP port on 127.0.0.1 that something else already holds."""
    holder = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    holder.bind(("127.0.0.1", 0))
    yield holder.getsockname()[1]
    holder.close()


def _query(port, name, tcp):
    raw = DNSRecord.question(name).send("127.0.0.1", port, tcp=tcp, timeout=2)
    return DNSRecord.parse(raw)


@pytest.mark.parametrize("tcp", [False, True], ids=["udp", "tcp"])
def test_r5_1_server_answers_real_queries(factory, tcp):
    service = DnsService(factory, "127.0.0.1", 0)
    service.start()
    try:
        reply = _query(service.port, "r1.lab.local", tcp)
        assert reply.header.aa == 1 and reply.header.rcode == RCODE.NOERROR
        assert str(reply.rr[0].rdata) == "192.168.198.11"
    finally:
        service.stop()


def test_r5_2_changes_are_answered_immediately(factory):
    """Design point 1: zones are read per query, so a new record needs no restart."""
    service = DnsService(factory, "127.0.0.1", 0)
    service.start()
    try:
        assert _query(service.port, "r2.lab.local", False).header.rcode == RCODE.NXDOMAIN
        with factory() as db:
            lab = db.query(zones.DnsZone).one()
            zones.create_record(db, lab, "r2", "A", "192.168.198.12")
            db.commit()
        assert str(_query(service.port, "r2.lab.local", False).rr[0].rdata) == "192.168.198.12"
    finally:
        service.stop()


def test_r5_1_stop_releases_both_ports(factory):
    """dnslib's own stop() only ends the loop; ours must also close the sockets."""
    service = DnsService(factory, "127.0.0.1", 0)
    service.start()
    port = service.port
    service.stop()
    assert not any(thread.is_alive() for thread in service.threads)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
        udp.bind(("127.0.0.1", port))  # would raise if the UDP socket leaked
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tcp:
        tcp.bind(("127.0.0.1", port))


def test_5_3_1_dns_bind_failure_is_logged_not_raised(factory, occupied_udp_port, caplog):
    with caplog.at_level(logging.ERROR):
        service = start_dns_service(factory, "127.0.0.1", occupied_udp_port)
    assert service is None
    message = caplog.text
    assert str(occupied_udp_port) in message and "DNS_PORT" in message  # says how to fix it


def test_5_3_1_app_and_syslog_keep_running_when_dns_cannot_bind(occupied_udp_port, monkeypatch):
    monkeypatch.setenv("DNS_ENABLED", "true")
    monkeypatch.setenv("DNS_HOST", "127.0.0.1")
    monkeypatch.setenv("DNS_PORT", str(occupied_udp_port))
    monkeypatch.setenv("SYSLOG_ENABLED", "true")
    monkeypatch.setenv("SYSLOG_HOST", "127.0.0.1")
    monkeypatch.setenv("SYSLOG_UDP_PORT", "0")
    monkeypatch.setenv("SYSLOG_TCP_PORT", "0")
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert app.state.dns_service is None
        assert app.state.syslog_receivers is not None  # syslog unaffected by the DNS failure


def test_5_3_1_app_keeps_running_when_syslog_cannot_bind(occupied_udp_port, monkeypatch):
    """The syslog fix approved in the DNS plan: previously this crashed app startup."""
    monkeypatch.setenv("SYSLOG_ENABLED", "true")
    monkeypatch.setenv("SYSLOG_HOST", "127.0.0.1")
    monkeypatch.setenv("SYSLOG_UDP_PORT", str(occupied_udp_port))
    monkeypatch.setenv("SYSLOG_TCP_PORT", "0")
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert app.state.syslog_receivers is None


def test_r5_1_dns_starts_from_the_lifespan_when_enabled(monkeypatch):
    monkeypatch.setenv("DNS_ENABLED", "true")
    monkeypatch.setenv("DNS_HOST", "127.0.0.1")
    monkeypatch.setenv("DNS_PORT", "0")
    with TestClient(app):
        service = app.state.dns_service
        assert service is not None and service.port > 0
    assert not any(thread.is_alive() for thread in service.threads)  # stopped on shutdown
