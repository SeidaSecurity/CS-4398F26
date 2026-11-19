import socket
import threading
from datetime import UTC, datetime

import pytest

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

    def capture(message, sender=None):
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


# --- R4.2: Cisco IOS format (real samples captured from the CML lab, 2026-11-19) -------------

RECEIVED = datetime(2026, 11, 19, 3, 38, 10, tzinfo=UTC)


@pytest.mark.parametrize(
    ("raw", "source", "severity", "body"),
    [
        (
            "<189>69: ios-lab-1: *Nov 19 03:38:07.246: %SYS-5-CONFIG_I: "
            "Configured from console by console",
            "ios-lab-1",
            5,
            "%SYS-5-CONFIG_I: Configured from console by console",
        ),
        (
            "<189>68: ios-lab-1: *Nov 19 03:38:06.042: %LINEPROTO-5-UPDOWN: Line protocol "
            "on Interface GigabitEthernet0/1, changed state to up",
            "ios-lab-1",
            5,
            "%LINEPROTO-5-UPDOWN: Line protocol on Interface GigabitEthernet0/1, "
            "changed state to up",
        ),
        (
            "<187>67: ios-lab-1: *Nov 19 03:38:05.042: %LINK-3-UPDOWN: Interface "
            "GigabitEthernet0/1, changed state to up",
            "ios-lab-1",
            3,
            "%LINK-3-UPDOWN: Interface GigabitEthernet0/1, changed state to up",
        ),
        (
            "<189>58: ios-lab-3: *Nov 19 03:28:07.995: %GRUB-5-CONFIG_WRITTEN: "
            "GRUB configuration was written to disk successfully.",
            "ios-lab-3",
            5,
            "%GRUB-5-CONFIG_WRITTEN: GRUB configuration was written to disk successfully.",
        ),
    ],
)
def test_r4_2_parses_real_cisco_ios_samples(raw, source, severity, body):
    record = parse_syslog(raw, RECEIVED)

    assert record["parsed"] is True
    assert record["source"] == source
    assert record["facility"] == 23  # local7, the IOS default
    assert record["severity"] == severity
    assert record["body"] == body
    assert record["raw_message"] == raw


def test_r4_2_unsynchronized_clock_uses_receive_time():
    """'*' means the router clock is not NTP-synced, so its time is not trusted."""
    record = parse_syslog(
        "<189>69: ios-lab-1: *Nov 19 03:38:07.246: %SYS-5-CONFIG_I: Configured", RECEIVED
    )
    assert record["timestamp"] == RECEIVED


def test_r4_2_synchronized_clock_uses_router_time_with_receive_year():
    record = parse_syslog(
        "<189>69: ios-lab-1: Nov 19 03:38:07.246: %SYS-5-CONFIG_I: Configured", RECEIVED
    )
    assert record["timestamp"] == datetime(2026, 11, 19, 3, 38, 7, 246000, tzinfo=UTC)


def test_r4_2_synchronized_time_with_explicit_year_and_timezone():
    record = parse_syslog(
        "<189>70: ios-lab-1: Nov 19 2026 03:38:07.246 UTC: %SYS-5-CONFIG_I: Configured",
        RECEIVED,
    )
    assert record["timestamp"] == datetime(2026, 11, 19, 3, 38, 7, 246000, tzinfo=UTC)


def test_r4_2_year_boundary_message_is_not_dated_in_the_future():
    """Boundary: sent Dec 31 23:59:59, received Jan 1 -> belongs to the previous year."""
    received = datetime(2027, 1, 1, 0, 0, 2, tzinfo=UTC)
    record = parse_syslog("<189>1: r1: Dec 31 23:59:59: %SYS-5-RESTART: up", received)
    assert record["timestamp"] == datetime(2026, 12, 31, 23, 59, 59, tzinfo=UTC)


@pytest.mark.parametrize(
    ("raw", "source"),
    # Cases: no origin-id hostname; no sequence number and no milliseconds; neither seq nor
    # hostname; '.' (clock was synced but lost) instead of '*'.
    [
        ("<189>69: *Nov 19 03:38:07.246: %SYS-5-CONFIG_I: Configured", "unknown"),
        ("<189>ios-lab-1: *Nov 19 03:38:07: %SYS-5-CONFIG_I: Configured", "ios-lab-1"),
        ("<189>*Nov 19 03:38:07.246: %SYS-5-CONFIG_I: Configured", "unknown"),
        ("<189>12: ios-lab-1: .Nov 19 03:38:07.246: %SYS-5-CONFIG_I: Configured", "ios-lab-1"),
    ],
)
def test_r4_2_cisco_optional_fields(raw, source):
    """Equivalence classes for the optional parts of the IOS header."""
    record = parse_syslog(raw, RECEIVED)
    assert record["parsed"] is True
    assert record["source"] == source
    assert record["body"] == "%SYS-5-CONFIG_I: Configured"


@pytest.mark.parametrize(
    ("raw", "parsed"),
    [
        ("<191>1: r1: *Nov 19 03:38:07: %SYS-7-DEBUG: x", True),  # boundary: highest valid PRI
        ("<192>1: r1: *Nov 19 03:38:07: %SYS-7-DEBUG: x", False),  # just above -> invalid
        ("<189>69: ios-lab-1: *Nov 19 03:38:07.246: no mnemonic here", False),  # not IOS-shaped
        ("<189>69: ios-lab-1: *Foo 99 03:38:07: %SYS-5-CONFIG_I: x", False),  # impossible date
    ],
)
def test_r4_2_cisco_boundaries_and_malformed_lines_are_kept_unparsed(raw, parsed):
    record = parse_syslog(raw, RECEIVED)
    assert record["parsed"] is parsed
    assert record["raw_message"] == raw  # never discarded (R4.2)


# --- R4.2/R4.3: fall back to the sender's IP when the message names no host -----------------


@pytest.mark.parametrize(
    ("raw", "expected_source"),
    [
        # hostname in the message wins over the sender address
        ("<189>69: ios-lab-1: *Nov 19 03:38:07: %SYS-5-CONFIG_I: x", "ios-lab-1"),
        # Cisco message without origin-id -> sender IP
        ("<189>69: *Nov 19 03:38:07: %SYS-5-CONFIG_I: x", "192.168.198.11"),
        # unparseable message -> sender IP instead of "unknown"
        ("garbage without any header", "192.168.198.11"),
    ],
)
def test_r4_3_source_falls_back_to_sender_address(raw, expected_source):
    record = parse_syslog(raw, RECEIVED, sender="192.168.198.11")
    assert record["source"] == expected_source


def test_r4_3_receivers_pass_the_sender_address(monkeypatch):
    received = []
    all_received = threading.Event()

    def capture(message, sender=None):
        received.append((message, sender))
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
        assert set(received) == {("udp test", "127.0.0.1"), ("tcp test", "127.0.0.1")}
    finally:
        receivers.stop()
