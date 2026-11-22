"""DHCP message codec (RFC 2131 §2 layout, RFC 2132 options, RFC 3396 split options).

Our own struct-based implementation (ADR-0007): the BOOTP fixed header (236 bytes), the magic
cookie at offset 236, then type-length-value options from offset 240.
"""

import ipaddress
import struct
from dataclasses import dataclass, field
from enum import IntEnum

MAGIC_COOKIE = b"\x63\x82\x53\x63"
BROADCAST_FLAG = 0x8000
BOOTREQUEST, BOOTREPLY = 1, 2
MIN_REPLY_LENGTH = 300  # classic BOOTP minimum; some clients drop shorter replies
_HEADER = struct.Struct("!BBBBIHH4s4s4s4s16s64s128s")  # 236 bytes
_ZERO = ipaddress.IPv4Address("0.0.0.0")

# Option codes used by this server (RFC 2132)
OPT_PAD, OPT_SUBNET_MASK, OPT_ROUTER, OPT_DNS, OPT_HOSTNAME, OPT_DOMAIN = 0, 1, 3, 6, 12, 15
OPT_REQUESTED_IP, OPT_LEASE_TIME, OPT_MESSAGE_TYPE, OPT_SERVER_ID = 50, 51, 53, 54
OPT_PARAMETER_LIST, OPT_CLIENT_ID, OPT_END = 55, 61, 255


class MessageType(IntEnum):
    DISCOVER = 1
    OFFER = 2
    REQUEST = 3
    DECLINE = 4
    ACK = 5
    NAK = 6
    RELEASE = 7
    INFORM = 8


class DhcpPacketError(ValueError):
    """The bytes are not a well-formed DHCP message."""


@dataclass
class DhcpMessage:
    op: int
    xid: int
    chaddr: bytes  # client hardware address (6 bytes for Ethernet)
    htype: int = 1
    hlen: int = 6
    hops: int = 0
    secs: int = 0
    flags: int = 0
    ciaddr: ipaddress.IPv4Address = _ZERO
    yiaddr: ipaddress.IPv4Address = _ZERO
    siaddr: ipaddress.IPv4Address = _ZERO
    giaddr: ipaddress.IPv4Address = _ZERO
    options: dict[int, bytes] = field(default_factory=dict)

    @property
    def message_type(self) -> MessageType | None:
        value = self.options.get(OPT_MESSAGE_TYPE)
        return MessageType(value[0]) if value else None

    @property
    def mac(self) -> str:
        return ":".join(f"{b:02x}" for b in self.chaddr[: self.hlen])

    @property
    def broadcast(self) -> bool:
        return bool(self.flags & BROADCAST_FLAG)

    def _ip_option(self, code: int) -> ipaddress.IPv4Address | None:
        value = self.options.get(code)
        return ipaddress.IPv4Address(value) if value is not None and len(value) == 4 else None

    @property
    def requested_ip(self) -> ipaddress.IPv4Address | None:
        return self._ip_option(OPT_REQUESTED_IP)

    @property
    def server_id(self) -> ipaddress.IPv4Address | None:
        return self._ip_option(OPT_SERVER_ID)

    @property
    def hostname(self) -> str | None:
        value = self.options.get(OPT_HOSTNAME)
        return value.decode("utf-8", errors="replace").strip("\x00") or None if value else None

    @property
    def parameter_request_list(self) -> list[int]:
        return list(self.options.get(OPT_PARAMETER_LIST, b""))


# --- option value helpers ------------------------------------------------------------------------


def encode_ip(address: str | ipaddress.IPv4Address) -> bytes:
    return ipaddress.IPv4Address(address).packed


def encode_ips(addresses: list[str]) -> bytes:
    return b"".join(encode_ip(address) for address in addresses)


def encode_u32(value: int) -> bytes:
    return value.to_bytes(4, "big")


# --- parse / build -------------------------------------------------------------------------------


def _parse_options(data: bytes) -> dict[int, bytes]:
    options: dict[int, bytes] = {}
    position = 0
    while position < len(data):
        code = data[position]
        if code == OPT_PAD:
            position += 1
            continue
        if code == OPT_END:
            break
        if position + 1 >= len(data):
            raise DhcpPacketError(f"Option {code} runs past the end of the packet.")
        length = data[position + 1]
        start, end = position + 2, position + 2 + length
        if end > len(data):
            raise DhcpPacketError(
                f"Option {code} (length {length}) runs past the end of the packet."
            )
        options[code] = options.get(code, b"") + data[start:end]  # RFC 3396 concatenation
        position = end
    return options


def parse(data: bytes) -> DhcpMessage:
    if len(data) < _HEADER.size + len(MAGIC_COOKIE):
        raise DhcpPacketError(f"Packet truncated: {len(data)} bytes, need at least 240.")
    (
        op,
        htype,
        hlen,
        hops,
        xid,
        secs,
        flags,
        ciaddr,
        yiaddr,
        siaddr,
        giaddr,
        chaddr,
        _sname,
        _file,
    ) = _HEADER.unpack_from(data)
    if op not in (BOOTREQUEST, BOOTREPLY):
        raise DhcpPacketError(f"Unknown op {op}; expected 1 (request) or 2 (reply).")
    if hlen > 16:
        raise DhcpPacketError(f"Invalid hardware address length {hlen} (maximum 16).")
    if data[_HEADER.size : _HEADER.size + 4] != MAGIC_COOKIE:
        raise DhcpPacketError("Missing DHCP magic cookie (not a DHCP message).")
    options = _parse_options(data[_HEADER.size + 4 :])
    message_type = options.get(OPT_MESSAGE_TYPE)
    if message_type is not None and (
        len(message_type) != 1 or message_type[0] not in MessageType._value2member_map_
    ):
        raise DhcpPacketError("Invalid DHCP message type option.")
    return DhcpMessage(
        op=op,
        xid=xid,
        chaddr=chaddr[:hlen],
        htype=htype,
        hlen=hlen,
        hops=hops,
        secs=secs,
        flags=flags,
        ciaddr=ipaddress.IPv4Address(ciaddr),
        yiaddr=ipaddress.IPv4Address(yiaddr),
        siaddr=ipaddress.IPv4Address(siaddr),
        giaddr=ipaddress.IPv4Address(giaddr),
        options=options,
    )


def build(message: DhcpMessage) -> bytes:
    header = _HEADER.pack(
        message.op,
        message.htype,
        message.hlen,
        message.hops,
        message.xid,
        message.secs,
        message.flags,
        message.ciaddr.packed,
        message.yiaddr.packed,
        message.siaddr.packed,
        message.giaddr.packed,
        message.chaddr.ljust(16, b"\x00")[:16],
        bytes(64),
        bytes(128),
    )
    body = bytearray(MAGIC_COOKIE)
    # Message type first, as clients conventionally expect.
    ordered = sorted(message.options.items(), key=lambda item: item[0] != OPT_MESSAGE_TYPE)
    for code, value in ordered:
        if len(value) > 255:
            raise DhcpPacketError(f"Option {code} value is {len(value)} bytes; the maximum is 255.")
        body += bytes([code, len(value)]) + value
    body.append(OPT_END)
    packet = header + bytes(body)
    return packet.ljust(MIN_REPLY_LENGTH, b"\x00")
