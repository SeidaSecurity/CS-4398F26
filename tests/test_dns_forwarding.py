"""R5.4: offline upstream-forwarding tests; no public DNS or CML lab required."""

import socket
import threading

import pytest
from dnslib import QTYPE, RCODE, RR, A, DNSRecord
from dnslib.server import BaseResolver, DNSLogger, DNSServer
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.dns import zones
from app.dns.forwarder import DnsForwarder
from app.dns.server import DnsService
from app.main import app


@pytest.fixture
def factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as db:
        zone = zones.create_zone(db, "lab.local")
        zones.create_record(db, zone, "router", "A", "192.168.198.11")
        db.commit()
    yield session_factory
    engine.dispose()


@pytest.fixture
def upstream():
    """A fake authoritative upstream on a loopback UDP socket."""

    class FakeUpstream(BaseResolver):
        calls: list[str] = []

        def resolve(self, request, handler):
            name = str(request.q.qname).lower().rstrip(".")
            self.calls.append(name)
            reply = request.reply(aa=0, ra=1)
            if name == "external.example":
                reply.add_answer(RR(name, QTYPE.A, ttl=42, rdata=A("203.0.113.42")))
            else:
                reply.header.rcode = RCODE.NXDOMAIN
            return reply

    fake = FakeUpstream()
    server = DNSServer(fake, address="127.0.0.1", port=0, tcp=False, logger=DNSLogger("-all"))
    port = server.server.server_address[1]
    thread = threading.Thread(target=server.server.serve_forever, daemon=True)
    thread.start()
    yield port, fake
    server.server.shutdown()
    server.server.server_close()
    thread.join(timeout=2)


def _ask(port: int, name: str) -> DNSRecord:
    return DNSRecord.parse(DNSRecord.question(name).send("127.0.0.1", port, timeout=2))


def test_r5_4_external_query_is_forwarded_with_answer_and_ttl(factory, upstream):
    upstream_port, fake = upstream
    service = DnsService(factory, "127.0.0.1", 0, "127.0.0.1", upstream_port)
    service.start()
    try:
        response = _ask(service.port, "external.example")
        assert response.header.rcode == RCODE.NOERROR
        assert response.header.aa == 0
        assert response.header.ra == 1
        assert len(response.rr) == 1
        assert str(response.rr[0].rdata) == "203.0.113.42"
        assert response.rr[0].ttl == 42
        assert fake.calls == ["external.example"]
    finally:
        service.stop()


def test_r5_4_local_answers_and_nxdomain_never_forwarded(factory, upstream):
    upstream_port, fake = upstream
    service = DnsService(factory, "127.0.0.1", 0, "127.0.0.1", upstream_port)
    service.start()
    try:
        local = _ask(service.port, "router.lab.local")
        missing = _ask(service.port, "missing.lab.local")
        assert local.header.aa == 1
        assert str(local.rr[0].rdata) == "192.168.198.11"
        assert missing.header.aa == 1 and missing.header.rcode == RCODE.NXDOMAIN
        assert fake.calls == []
    finally:
        service.stop()


def test_r5_4_upstream_nxdomain_passes_through(factory, upstream):
    upstream_port, _ = upstream
    service = DnsService(factory, "127.0.0.1", 0, "127.0.0.1", upstream_port)
    service.start()
    try:
        response = _ask(service.port, "missing.example")
        assert response.header.rcode == RCODE.NXDOMAIN and response.header.aa == 0
    finally:
        service.stop()


def test_r5_4_unconfigured_upstream_preserves_refused(factory):
    service = DnsService(factory, "127.0.0.1", 0)
    service.start()
    try:
        response = _ask(service.port, "external.example")
        assert response.header.rcode == RCODE.REFUSED
        assert response.header.aa == 0
    finally:
        service.stop()


def test_r5_4_upstream_timeout_returns_servfail_not_server_crash(factory):
    # Keep this dummy UDP socket bound but never reply, forcing a reliable timeout.
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as dummy:
        dummy.bind(("127.0.0.1", 0))
        unused_port = dummy.getsockname()[1]
        service = DnsService(factory, "127.0.0.1", 0, "127.0.0.1", unused_port, 0.05)
        service.start()
        try:
            response = _ask(service.port, "external.example")
            assert response.header.rcode == RCODE.SERVFAIL
            assert response.header.aa == 0
            assert _ask(service.port, "router.lab.local").header.rcode == RCODE.NOERROR
        finally:
            service.stop()


def test_r5_4_rejects_unrelated_response_id(monkeypatch):
    def unrelated(self, host, port, tcp=False, timeout=None):
        reply = self.reply(ra=1)
        reply.header.id ^= 1
        return reply.pack()

    monkeypatch.setattr(DNSRecord, "send", unrelated)
    response = DnsForwarder("127.0.0.1").forward(DNSRecord.question("example.org"))
    assert response.header.rcode == RCODE.SERVFAIL


def test_r5_4_falls_back_to_tcp_if_upstream_truncates_udp(monkeypatch):
    protocols = []

    def truncated_udp(self, host, port, tcp=False, timeout=None):
        protocols.append("tcp" if tcp else "udp")
        reply = self.reply(ra=1)
        if not tcp:
            reply.header.tc = 1
        else:
            reply.add_answer(RR("example.org", QTYPE.A, ttl=30, rdata=A("203.0.113.1")))
        return reply.pack()

    monkeypatch.setattr(DNSRecord, "send", truncated_udp)
    response = DnsForwarder("127.0.0.1").forward(DNSRecord.question("example.org"))
    assert protocols == ["udp", "tcp"]
    assert response.header.rcode == RCODE.NOERROR
    assert str(response.rr[0].rdata) == "203.0.113.1"


@pytest.mark.parametrize(
    ("host", "port", "timeout"),
    [
        ("upstream.local", 53, 1),
        ("0.0.0.0", 53, 1),
        ("255.255.255.255", 53, 1),
        ("224.0.0.1", 53, 1),
        ("127.0.0.1", 0, 1),
        ("127.0.0.1", 65536, 1),
        ("127.0.0.1", 53, 0),
        ("127.0.0.1", 53, 11),
    ],
)
def test_r5_4_rejects_invalid_upstream_configuration(host, port, timeout):
    with pytest.raises(ValueError):
        DnsForwarder(host, port, timeout)


def test_r5_4_refuses_to_forward_to_itself(factory):
    with pytest.raises(ValueError, match="this DNS listener"):
        DnsService(factory, "127.0.0.1", 5353, "127.0.0.1", 5353)


def test_r5_4_bad_upstream_setting_does_not_break_app_lifespan(monkeypatch):
    monkeypatch.setenv("DNS_ENABLED", "true")
    monkeypatch.setenv("DNS_UPSTREAM_HOST", "127.0.0.1")
    monkeypatch.setenv("DNS_UPSTREAM_PORT", "not-a-port")
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert app.state.dns_service is None
