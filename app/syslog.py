import re
import socketserver
import threading
from datetime import UTC, datetime, timedelta
from typing import TypedDict

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import LogRecord


class ParsedMessage(TypedDict):
    timestamp: datetime
    source: str
    facility: int | None
    severity: int | None
    body: str
    raw_message: str
    parsed: bool


RFC5424 = re.compile(
    r"^<(?P<pri>\d{1,3})>1 "
    r"(?P<timestamp>\S+) (?P<host>\S+) \S+ \S+ \S+ \S+ ?(?P<body>.*)$"
)
RFC3164 = re.compile(
    r"^<(?P<pri>\d{1,3})>(?P<timestamp>[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}) "
    r"(?P<host>\S+) (?P<body>.*)$"
)
# Cisco IOS default format (not RFC-conformant), e.g. from the CML lab:
#   <187>67: ios-lab-1: *Nov 19 03:38:05.042: %LINK-3-UPDOWN: Interface Gi0/1, changed state to up
# seq number and hostname (`logging origin-id hostname`) are optional; '*' or '.' before the time
# means the router clock is not synchronized; year/milliseconds/timezone are optional.
CISCO_IOS = re.compile(
    r"^<(?P<pri>\d{1,3})>"
    r"(?:(?P<seq>\d+): )?"
    r"(?:(?P<host>[^\s:*.][^\s:]*): )?"
    r"(?P<unsync>[*.])?"
    r"(?P<month>[A-Z][a-z]{2})\s+(?P<day>\d{1,2})(?:\s+(?P<year>\d{4}))?\s+"
    r"(?P<time>\d{2}:\d{2}:\d{2})(?:\.(?P<fraction>\d{1,6}))?"
    r"(?:\s+[A-Za-z]{2,5})?: "
    r"(?P<body>%[A-Z0-9_]+-[0-7]-[A-Z0-9_]+:.*)$"
)


def _cisco_timestamp(match: re.Match[str], received_at: datetime) -> datetime:
    """Router time, or receive time when the router clock is unsynchronized ('*' or '.').

    Raises ValueError for an impossible date, so malformed lines stay unparsed.
    The router's time has no timezone; like RFC 3164 handling, it is treated as UTC.
    """
    year = int(match.group("year") or received_at.year)
    fraction = (match.group("fraction") or "0").ljust(6, "0")
    router_time = datetime.strptime(
        f"{year} {match.group('month')} {match.group('day')} {match.group('time')}",
        "%Y %b %d %H:%M:%S",
    ).replace(microsecond=int(fraction), tzinfo=UTC)
    if match.group("unsync"):
        return received_at
    # No year in the message: a "Dec 31" line received on Jan 1 belongs to the previous year.
    if not match.group("year") and router_time > received_at + timedelta(days=1):
        router_time = router_time.replace(year=year - 1)
    return router_time


def parse_syslog(
    raw_message: str, received_at: datetime | None = None, sender: str | None = None
) -> ParsedMessage:
    """Parse RFC 5424, Cisco IOS, or RFC 3164; keep anything else as unparsed (R4.2).

    ``sender`` (the peer IP) is the source when the message itself names no host.
    """
    received_at = received_at or datetime.now(UTC)
    fallback_source = sender or "unknown"
    message = raw_message.strip()
    match = RFC5424.match(message)
    parsed_timestamp: datetime | None = None

    if match:
        timestamp = match.group("timestamp")
        try:
            parsed_timestamp = (
                datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                if timestamp != "-"
                else None
            )
        except ValueError:
            match = None
    elif match := CISCO_IOS.match(message):
        try:
            parsed_timestamp = _cisco_timestamp(match, received_at)
        except ValueError:
            match = None
    else:
        match = RFC3164.match(message)
        if match:
            try:
                parsed_timestamp = datetime.strptime(
                    f"{received_at.year} {match.group('timestamp')}", "%Y %b %d %H:%M:%S"
                ).replace(tzinfo=UTC)
            except ValueError:
                match = None

    if match is None or int(match.group("pri")) > 191:
        return {
            "timestamp": received_at,
            "source": fallback_source,
            "facility": None,
            "severity": None,
            "body": message,
            "raw_message": raw_message,
            "parsed": False,
        }

    priority = int(match.group("pri"))
    return {
        "timestamp": parsed_timestamp or received_at,
        "source": match.group("host") or fallback_source,
        "facility": priority // 8,
        "severity": priority % 8,
        "body": match.group("body"),
        "raw_message": raw_message,
        "parsed": True,
    }


def persist_message(raw_message: str, sender: str | None = None) -> None:
    parsed = parse_syslog(raw_message, sender=sender)
    with SessionLocal() as session:
        session.add(LogRecord(**parsed))
        session.commit()


class _UDPHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        persist_message(
            self.request[0].decode("utf-8", errors="replace"), sender=self.client_address[0]
        )


class _TCPHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        for line in self.rfile:
            if line:
                persist_message(
                    line.rstrip(b"\r\n").decode("utf-8", errors="replace"),
                    sender=self.client_address[0],
                )


class SyslogReceivers:
    def __init__(self, host: str, udp_port: int, tcp_port: int) -> None:
        udp_server = socketserver.ThreadingUDPServer((host, udp_port), _UDPHandler)
        try:
            tcp_server = socketserver.ThreadingTCPServer((host, tcp_port), _TCPHandler)
        except OSError:
            udp_server.server_close()
            raise
        udp_server.daemon_threads = True
        tcp_server.daemon_threads = True
        self.servers: list[socketserver.BaseServer] = [udp_server, tcp_server]
        self.threads: list[threading.Thread] = []

    def start(self) -> None:
        for server in self.servers:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.threads.append(thread)

    def stop(self) -> None:
        for server in self.servers:
            server.shutdown()
            server.server_close()
        for thread in self.threads:
            thread.join(timeout=2)


LIKE_ESCAPE = "\\"


def escape_like(text: str) -> str:
    """Escape LIKE wildcards so operator search text is matched literally (R4.3)."""
    return (
        text.replace(LIKE_ESCAPE, LIKE_ESCAPE * 2)
        .replace("%", LIKE_ESCAPE + "%")
        .replace("_", LIKE_ESCAPE + "_")
    )


def list_logs(
    session: Session,
    query: str | None,
    source: str | None,
    severity: int | None,
    since: datetime | None,
    until: datetime | None,
    limit: int,
) -> list[LogRecord]:
    from sqlalchemy import select

    statement = select(LogRecord)
    if query:
        statement = statement.where(
            LogRecord.body.ilike(f"%{escape_like(query)}%", escape=LIKE_ESCAPE)
        )
    if source:
        statement = statement.where(LogRecord.source == source)
    if severity is not None:
        statement = statement.where(LogRecord.severity == severity)
    if since:
        statement = statement.where(LogRecord.timestamp >= since)
    if until:
        statement = statement.where(LogRecord.timestamp <= until)
    statement = statement.order_by(LogRecord.timestamp.desc()).limit(limit)
    return list(session.scalars(statement))
