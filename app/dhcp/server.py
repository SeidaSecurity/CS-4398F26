"""DHCP UDP server lifecycle (R6.1, R6.6; SRS 5.3.1). Decisions in ADR-0007.

A plain UDP socket with SO_BROADCAST (no raw sockets, no scapy), bound to DHCP_SERVER_IP rather
than 0.0.0.0: on Windows a socket bound to one address only receives broadcasts from that
interface, so a multi-homed PC never answers on its real network (checkpoint G).
"""

import ipaddress
import logging
import socket
import threading
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dhcp.allocator import Allocator
from app.dhcp.packet import DhcpMessage, DhcpPacketError, MessageType, build, parse
from app.dhcp.pools import network_of
from app.models import DhcpPool

log = logging.getLogger(__name__)
SERVER_PORT, CLIENT_PORT = 67, 68
_ZERO = ipaddress.IPv4Address("0.0.0.0")


class DhcpService:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        server_ip: str,
        bind_host: str | None = None,
        port: int = SERVER_PORT,
        reply_host: str = "255.255.255.255",
        reply_port: int = CLIENT_PORT,
        sweep_interval: float = 60.0,
    ) -> None:
        self.session_factory = session_factory
        self.server_ip = ipaddress.IPv4Address(server_ip)
        self.reply_host, self.reply_port = reply_host, reply_port
        self.sweep_interval = sweep_interval
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            self.sock.bind((bind_host or str(self.server_ip), port))
        except OSError:
            self.sock.close()
            raise
        self.sock.settimeout(0.5)  # lets the loop notice stop()
        self.bound_address, self.port = self.sock.getsockname()[:2]
        self._stopping = threading.Event()
        self.threads: list[threading.Thread] = []

    def start(self) -> None:
        for target in (self._serve, self._sweep):
            thread = threading.Thread(target=target, daemon=True)
            thread.start()
            self.threads.append(thread)

    def stop(self) -> None:
        self._stopping.set()
        for thread in self.threads:
            thread.join(timeout=2)
        self.sock.close()

    # --- loops -----------------------------------------------------------------------------------

    def _serve(self) -> None:
        while not self._stopping.is_set():
            try:
                data, sender = self.sock.recvfrom(4096)
            except TimeoutError:
                continue
            except OSError:
                if self._stopping.is_set():
                    return
                continue  # e.g. Windows ICMP "port unreachable" from an earlier send
            try:
                request = parse(data)
            except DhcpPacketError as exc:
                log.debug("Ignoring malformed DHCP packet from %s: %s", sender[0], exc)
                continue
            try:
                with self.session_factory() as db:
                    reply = Allocator(db, self.server_ip).handle(request)
                if reply is not None:
                    self.sock.sendto(build(reply), self._destination(request, reply))
            except Exception:  # one bad packet must not stop the service
                log.exception(
                    "DHCP failed to handle a %s from %s", request.message_type, request.mac
                )

    def _sweep(self) -> None:
        while not self._stopping.wait(self.sweep_interval):
            try:
                with self.session_factory() as db:
                    removed = Allocator(db, self.server_ip).sweep()
                if removed:
                    log.info("DHCP released %d expired lease(s)", removed)
            except Exception:
                log.exception("DHCP lease sweep failed")

    def _destination(self, request: DhcpMessage, reply: DhcpMessage) -> tuple[str, int]:
        """RFC 2131 §4.1: relay → giaddr:67; renewal → client's address; else broadcast."""
        if request.giaddr != _ZERO:
            return str(request.giaddr), SERVER_PORT
        if reply.message_type is not MessageType.NAK and request.ciaddr != _ZERO:
            return str(request.ciaddr), self.reply_port
        return self.reply_host, self.reply_port


def _is_local_address(address: str) -> bool:
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.bind((address, 0))
        return True
    except OSError:
        return False
    finally:
        probe.close()


def start_dhcp_service(
    session_factory: Callable[[], Session],
    server_ip: str,
    bind_host: str | None = None,
    port: int = SERVER_PORT,
) -> DhcpService | None:
    """Start DHCP only where it is safe (checkpoint B); otherwise log why and return None."""
    try:
        address = ipaddress.IPv4Address(server_ip.strip())
    except ValueError:
        log.error(
            "DHCP stays off: DHCP_SERVER_IP is missing or not an IPv4 address. Set it to this "
            "computer's address on the isolated DHCP lab network."
        )
        return None
    if not _is_local_address(str(address)):
        log.error(
            "DHCP stays off: %s is not an address of this computer. Set DHCP_SERVER_IP to the "
            "lab adapter's address (see 'ipconfig').",
            address,
        )
        return None
    with session_factory() as db:
        match = next((p for p in db.scalars(select(DhcpPool)) if address in network_of(p)), None)
    if match is None:
        log.error(
            "DHCP stays off: no pool contains %s, so this server would have no network to serve. "
            "Create a pool for that subnet on the Services screen, then restart.",
            address,
        )
        return None
    if bind_host == "0.0.0.0":
        log.warning(
            "DHCP is listening on ALL interfaces (DHCP_BIND_HOST=0.0.0.0); use only "
            "on a host whose sole interface is the isolated lab network."
        )
    try:
        service = DhcpService(session_factory, str(address), bind_host=bind_host, port=port)
    except OSError as exc:
        log.error(
            "DHCP could not listen on %s:%s (%s). Another DHCP server may be running: check "
            "'Get-NetUDPEndpoint -LocalPort %s'. The rest of the application keeps running.",
            bind_host or address,
            port,
            exc,
            port,
        )
        return None
    service.start()
    log.info(
        "DHCP serving pool '%s' (%s) on %s:%s",
        match.name,
        match.subnet,
        service.bound_address,
        service.port,
    )
    return service
