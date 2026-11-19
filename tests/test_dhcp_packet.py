"""DHCP packet codec on raw bytes (RFC 2131 §2, RFC 2132). Checkpoint A of the DHCP plan.

Packets are hand-assembled field by field from the RFC layout, so the tests check the codec
against the standard, not against itself.
"""

import ipaddress
import struct

import pytest

from app.dhcp.packet import (
    BROADCAST_FLAG,
    MAGIC_COOKIE,
    DhcpMessage,
    DhcpPacketError,
    MessageType,
    build,
    encode_ip,
    encode_ips,
    encode_u32,
    parse,
)

MAC = bytes.fromhex("aabbccddee01")
XID = 0x3903F326


def raw_packet(
    op=1,
    htype=1,
    hlen=6,
    xid=XID,
    flags=0,
    ciaddr="0.0.0.0",
    giaddr="0.0.0.0",
    chaddr=MAC,
    cookie=MAGIC_COOKIE,
    options=b"\x35\x01\x01\xff",
):
    """Assemble a packet exactly as RFC 2131 §2 lays it out."""
    header = struct.pack(
        "!BBBBIHH4s4s4s4s16s64s128s",
        op,
        htype,
        hlen,
        0,
        xid,
        0,
        flags,
        ipaddress.IPv4Address(ciaddr).packed,
        bytes(4),
        bytes(4),
        ipaddress.IPv4Address(giaddr).packed,
        chaddr.ljust(16, b"\x00"),
        bytes(64),
        bytes(128),
    )
    assert len(header) == 236
    return header + cookie + options


# --- parsing -------------------------------------------------------------------------------------


def test_r6_1_parses_a_discover():
    options = (
        b"\x35\x01\x01"  # 53 message type = DISCOVER
        b"\x0c\x05host1"  # 12 hostname
        b"\x32\x04\xc0\xa8\x32\x65"  # 50 requested IP 192.168.50.101
        b"\x37\x03\x01\x03\x06"  # 55 parameter request list: mask, router, DNS
        b"\x00\x00"  # pad bytes are skipped
        b"\xff"
    )
    message = parse(raw_packet(flags=BROADCAST_FLAG, options=options))
    assert message.op == 1 and message.xid == XID
    assert message.message_type is MessageType.DISCOVER
    assert message.mac == "aa:bb:cc:dd:ee:01"
    assert message.broadcast is True
    assert message.hostname == "host1"
    assert message.requested_ip == ipaddress.IPv4Address("192.168.50.101")
    assert message.parameter_request_list == [1, 3, 6]


def test_r6_1_parses_relay_and_renewal_addresses():
    message = parse(raw_packet(ciaddr="192.168.50.100", giaddr="10.0.0.1"))
    assert message.ciaddr == ipaddress.IPv4Address("192.168.50.100")
    assert message.giaddr == ipaddress.IPv4Address("10.0.0.1")


def test_r6_1_split_options_are_concatenated_rfc3396():
    options = b"\x35\x01\x01\x0c\x03hos\x0c\x02t1\xff"
    assert parse(raw_packet(options=options)).hostname == "host1"


def test_r6_1_missing_end_option_is_tolerated():
    assert parse(raw_packet(options=b"\x35\x01\x03")).message_type is MessageType.REQUEST


def test_r6_1_malformed_typed_option_is_treated_as_absent():
    message = parse(raw_packet(options=b"\x35\x01\x03\x32\x03\xc0\xa8\x32\xff"))
    assert message.requested_ip is None  # option 50 must be exactly 4 bytes


@pytest.mark.parametrize(
    ("packet", "message"),
    [
        (raw_packet()[:239], "truncated"),  # 1 byte short of header + cookie
        (raw_packet(cookie=b"\x63\x82\x53\x64"), "magic cookie"),
        (raw_packet(options=b"\x35\x01\x01\x0c\x09ab"), "past the end"),  # length 9, only 2 bytes
        (raw_packet(options=b"\x35\x01\x01\x0c"), "past the end"),  # code with no length byte
        (raw_packet(op=3), "op"),
        (raw_packet(hlen=17), "hardware address length"),
        (raw_packet(options=b"\x35\x02\x01\x01\xff"), "message type"),  # wrong length
        (raw_packet(options=b"\x35\x01\x09\xff"), "message type"),  # 9 is not a DHCP type
    ],
)
def test_r6_1_malformed_packets_are_rejected(packet, message):
    with pytest.raises(DhcpPacketError, match=message):
        parse(packet)


# --- building ------------------------------------------------------------------------------------


def offer():
    return DhcpMessage(
        op=2,
        xid=XID,
        chaddr=MAC,
        flags=BROADCAST_FLAG,
        yiaddr=ipaddress.IPv4Address("192.168.50.100"),
        siaddr=ipaddress.IPv4Address("192.168.50.1"),
        options={
            53: bytes([MessageType.OFFER]),
            54: encode_ip("192.168.50.1"),
            51: encode_u32(3600),
            1: encode_ip("255.255.255.0"),
            3: encode_ip("192.168.50.1"),
            6: encode_ips(["192.168.50.1", "8.8.8.8"]),
            15: b"lab.local",
        },
    )


def test_r6_1_built_offer_has_rfc_byte_layout():
    data = build(offer())
    assert data[0] == 2 and data[1] == 1 and data[2] == 6  # op=BOOTREPLY, ethernet, 6-byte MAC
    assert data[4:8] == XID.to_bytes(4, "big")
    assert data[10:12] == b"\x80\x00"  # broadcast flag
    assert data[16:20] == bytes([192, 168, 50, 100])  # yiaddr
    assert data[20:24] == bytes([192, 168, 50, 1])  # siaddr
    assert data[28:34] == MAC and data[34:44] == bytes(10)  # chaddr padded to 16
    assert data[236:240] == MAGIC_COOKIE
    assert data[240:243] == b"\x35\x01\x02"  # message type first, = OFFER
    assert b"\x33\x04\x00\x00\x0e\x10" in data  # 51 lease time 3600
    assert b"\x06\x08\xc0\xa8\x32\x01\x08\x08\x08\x08" in data  # 6 DNS servers, 2 x 4 bytes
    # Walk the TLVs to find END (a plain search for 0xff would hit the 255.255.255.0 mask).
    end = 240
    while data[end] != 0xFF:
        end += 2 + data[end + 1]
    assert data[end + 1 :] == bytes(len(data) - end - 1)  # zero padding after END


def test_r6_1_replies_are_padded_to_the_bootp_minimum():
    assert len(build(offer())) >= 300


def test_r6_1_build_then_parse_round_trips():
    original = offer()
    parsed = parse(build(original))
    assert (parsed.op, parsed.xid, parsed.mac, parsed.flags) == (
        2,
        XID,
        "aa:bb:cc:dd:ee:01",
        BROADCAST_FLAG,
    )
    assert parsed.yiaddr == original.yiaddr and parsed.siaddr == original.siaddr
    assert parsed.message_type is MessageType.OFFER
    assert parsed.options == original.options


def test_r6_1_oversized_option_is_refused_when_building():
    message = offer()
    message.options[15] = b"x" * 256
    with pytest.raises(DhcpPacketError, match="255"):
        build(message)
