"""UDP + TCP DNS server lifecycle (R5.1, SRS 5.3.1). Answering logic lives in resolver.py."""

import logging
import threading
from collections.abc import Callable

from dnslib.server import DNSLogger, DNSServer
from sqlalchemy.orm import Session

from app.dns.forwarder import DnsForwarder
from app.dns.resolver import DatabaseResolver

log = logging.getLogger(__name__)
# dnslib prints every request by default; keep only its error output.
_QUIET = DNSLogger(log="-request,-reply,-truncated,-recv,-send,-data", prefix=False)


class DnsService:
    """Owns one UDP and one TCP dnslib server on the same port."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        host: str,
        port: int,
        upstream_host: str | None = None,
        upstream_port: int = 53,
        forward_timeout: float = 2.0,
    ) -> None:
        if upstream_host and upstream_port == port and (
            upstream_host == host or (host == "0.0.0.0" and upstream_host == "127.0.0.1")
        ):
            raise ValueError("DNS upstream must not point at this DNS listener")
        forwarder = (
            DnsForwarder(upstream_host, upstream_port, forward_timeout)
            if upstream_host else None
        )
        resolver = DatabaseResolver(session_factory, forwarder)
        self.udp = DNSServer(resolver, address=host, port=port, tcp=False, logger=_QUIET)
        self.port: int = self.udp.server.server_address[1]  # resolves port 0 to the real one
        try:
            self.tcp = DNSServer(resolver, address=host, port=self.port, tcp=True, logger=_QUIET)
        except OSError:
            self.udp.server.server_close()
            raise
        self.threads: list[threading.Thread] = []

    def start(self) -> None:
        for server in (self.udp, self.tcp):
            thread = threading.Thread(target=server.server.serve_forever, daemon=True)
            thread.start()
            self.threads.append(thread)

    def stop(self) -> None:
        # dnslib's DNSServer.stop() only ends the loop; close the sockets so the port is freed.
        for server in (self.udp, self.tcp):
            server.server.shutdown()
            server.server.server_close()
        for thread in self.threads:
            thread.join(timeout=2)


def start_dns_service(
    session_factory: Callable[[], Session],
    host: str,
    port: int,
    upstream_host: str | None = None,
    upstream_port: int = 53,
    forward_timeout: float = 2.0,
) -> DnsService | None:
    """Start DNS, or log why it couldn't and return None, so the rest of the app keeps running."""
    try:
        service = DnsService(
            session_factory, host, port, upstream_host, upstream_port, forward_timeout
        )
    except (OSError, ValueError) as exc:
        log.error(
            "DNS could not start on %s:%s (%s). Check DNS_PORT, DNS_UPSTREAM_HOST, "
            "DNS_UPSTREAM_PORT and DNS_FORWARD_TIMEOUT, or find a port conflict "
            "with 'Get-NetUDPEndpoint -LocalPort %s'. "
            "The rest of the application keeps running.",
            host or "0.0.0.0", port, exc, port,
        )
        return None
    service.start()
    log.info("DNS listening on %s:%s (UDP and TCP)", host or "0.0.0.0", service.port)
    return service
