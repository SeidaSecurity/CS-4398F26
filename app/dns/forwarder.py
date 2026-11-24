"""Optional upstream DNS forwarding (SRS R5.4).

The forwarding transport is kept out of the authoritative resolver so local
zones continue to work when the upstream server is unavailable.  A literal
IPv4 address is required: looking up an upstream *hostname* using our own DNS
service could create a resolution loop.
"""

import ipaddress
import logging

from dnslib import RCODE, DNSRecord

log = logging.getLogger(__name__)


class DnsForwarder:
    """Forward an outside-zone query over UDP, retrying over TCP if truncated."""

    def __init__(self, host: str, port: int = 53, timeout: float = 2.0) -> None:
        try:
            address = ipaddress.IPv4Address(host)
        except ipaddress.AddressValueError as exc:
            raise ValueError("DNS_UPSTREAM_HOST must be a literal IPv4 address") from exc
        if address.is_unspecified or address.is_multicast or str(address) == "255.255.255.255":
            raise ValueError("DNS_UPSTREAM_HOST must be a unicast IPv4 address")
        if not 1 <= port <= 65535:
            raise ValueError("DNS_UPSTREAM_PORT must be between 1 and 65535")
        if not 0 < timeout <= 10:
            raise ValueError("DNS_FORWARD_TIMEOUT must be > 0 and <= 10 seconds")
        self.host = str(address)
        self.port = port
        self.timeout = timeout

    @staticmethod
    def _valid_response(request: DNSRecord, response: DNSRecord) -> bool:
        return (
            response.header.qr == 1
            and response.header.id == request.header.id
            and str(response.q.qname).lower() == str(request.q.qname).lower()
            and response.q.qtype == request.q.qtype
            and response.q.qclass == request.q.qclass
        )

    def forward(self, request: DNSRecord) -> DNSRecord:
        """Return upstream's result or an operator-safe SERVFAIL if it cannot be used.

        Only the configured upstream is contacted, not an arbitrary IP from the
        request. This avoids turning the API into an open DNS relay selector.
        """
        try:
            response = DNSRecord.parse(
                request.send(self.host, self.port, tcp=False, timeout=self.timeout)
            )
            if not self._valid_response(request, response):
                raise ValueError("upstream returned an unrelated DNS response")
            if response.header.tc:
                response = DNSRecord.parse(
                    request.send(self.host, self.port, tcp=True, timeout=self.timeout)
                )
                if not self._valid_response(request, response) or response.header.tc:
                    raise ValueError("upstream TCP reply was invalid or truncated")
            # We are forwarding, not an authoritative source for the outside name.
            response.header.aa = 0
            return response
        except Exception as exc:
            # Network timeouts and malformed DNS responses are normal failures;
            # do not crash the DNS worker or expose upstream internals to clients.
            log.warning("DNS upstream %s:%s failed: %s", self.host, self.port, exc)
            reply = request.reply(aa=0, ra=1)
            reply.header.rcode = RCODE.SERVFAIL
            return reply
