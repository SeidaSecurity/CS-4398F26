import socket
import threading
from datetime import UTC, datetime

from app.syslog import SyslogReceivers, parse_syslog


def test_parse_rfc5424_message():
    record = parse_syslog(
        "<13>1 2025-02-01T12:00:00Z router1 app - ID47 - link changed",
        datetime(2025, 2, 1, tzinfo=UTC),
    )

    assert record["parsed"] is True
    assert record["facility"] == 1
    assert record["severity"] == 5
    assert record["source"] == "router1"
    assert record["body"] == "link changed"
    assert record["timestamp"] == datetime(2025, 2, 1, 12, tzinfo=UTC)


def test_parse_rfc3164_message():
    record = parse_syslog(
        "<34>Feb  1 12:00:00 switch1 %LINK-3-UPDOWN: Interface changed",
        datetime(2025, 2, 1, tzinfo=UTC),
    )

    assert record["parsed"] is True
    assert record["facility"] == 4
    assert record["severity"] == 2
    assert record["source"] == "switch1"
    assert record["body"] == "%LINK-3-UPDOWN: Interface changed"


def test_preserve_unparsed_message():
    raw = "not a syslog message"
    record = parse_syslog(raw)

    assert record["parsed"] is False
    assert record["raw_message"] == raw
    assert record["body"] == raw


def test_preserve_message_with_invalid_timestamp():
    raw = "<13>1 not-a-timestamp router1 app - ID47 - message"

    record = parse_syslog(raw)

    assert record["parsed"] is False
    assert record["raw_message"] == raw


def test_preserve_message_with_invalid_priority():
    raw = "<200>1 2025-02-01T12:00:00Z router1 app - ID47 - message"

    record = parse_syslog(raw)

    assert record["parsed"] is False


def test_udp_and_tcp_receivers_forward_messages(monkeypatch):
    received = []
    all_received = threading.Event()

    def capture(message):
        received.append(message)
        if len(received) == 2:
            all_received.set()

    monkeypatch.setattr("app.syslog.persist_message", capture)
    receivers = SyslogReceivers("127.0.0.1", 0, 0)
    udp_port = receivers.servers[0].server_address[1]
    tcp_port = receivers.servers[1].server_address[1]
    receivers.start()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
            udp.sendto(b"udp test", ("127.0.0.1", udp_port))
        with socket.create_connection(("127.0.0.1", tcp_port), timeout=2) as tcp:
            tcp.sendall(b"tcp test\n")
        assert all_received.wait(timeout=2)
        assert set(received) == {"udp test", "tcp test"}
    finally:
        receivers.stop()
