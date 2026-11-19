import re
import socketserver
import threading
from datetime import UTC, datetime
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


def parse_syslog(raw_message: str, received_at: datetime | None = None) -> ParsedMessage:
    received_at = received_at or datetime.now(UTC)
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
            "source": "unknown",
            "facility": None,
            "severity": None,
            "body": message,
            "raw_message": raw_message,
            "parsed": False,
        }

    priority = int(match.group("pri"))
    return {
        "timestamp": parsed_timestamp or received_at,
        "source": match.group("host"),
        "facility": priority // 8,
        "severity": priority % 8,
        "body": match.group("body"),
        "raw_message": raw_message,
        "parsed": True,
    }


def persist_message(raw_message: str) -> None:
    parsed = parse_syslog(raw_message)
    with SessionLocal() as session:
        session.add(LogRecord(**parsed))
        session.commit()


class _UDPHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        persist_message(self.request[0].decode("utf-8", errors="replace"))


class _TCPHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        for line in self.rfile:
            if line:
                persist_message(line.rstrip(b"\r\n").decode("utf-8", errors="replace"))


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
