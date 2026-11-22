"""DHCP REST API (R6.2, R6.3, R6.4, R4.4). Checkpoints B (pool deletion) and C (release frees)."""

import ipaddress

from conftest import sign_in
from sqlalchemy import select

from app.dhcp.allocator import Allocator
from app.dhcp.packet import BOOTREQUEST, BROADCAST_FLAG, DhcpMessage, MessageType, encode_ip
from app.models import AuditRecord, DhcpLease, DhcpReservation

BASE = "/api/v1/dhcp"
POOL = {
    "name": "lab-clients",
    "subnet": "192.168.50.0/24",
    "range_start": "192.168.50.100",
    "range_end": "192.168.50.199",
    "gateway": "192.168.50.1",
    "dns_servers": ["192.168.50.1"],
    "domain": "lab.local",
    "lease_seconds": 3600,
}


def _admin(api):
    client, factory = api
    sign_in(client, factory, "ada", "admin")
    return client, factory


def _pool(client, **changes):
    return client.post(f"{BASE}/pools", json={**POOL, **changes})


def _discover_and_bind(factory, n):
    """Get a real lease through the allocator, as a client on the segment would."""
    mac = bytes.fromhex(f"aabbccddee{n:02x}")
    with factory() as db:
        allocator = Allocator(db, "192.168.50.1")
        offer = allocator.handle(
            DhcpMessage(
                op=BOOTREQUEST,
                xid=n,
                chaddr=mac,
                flags=BROADCAST_FLAG,
                options={53: bytes([MessageType.DISCOVER])},
            )
        )
        allocator.handle(
            DhcpMessage(
                op=BOOTREQUEST,
                xid=n,
                chaddr=mac,
                flags=BROADCAST_FLAG,
                options={
                    53: bytes([MessageType.REQUEST]),
                    50: encode_ip(offer.yiaddr),
                    54: encode_ip("192.168.50.1"),
                },
            )
        )
        return str(offer.yiaddr)


def _audit(factory):
    with factory() as db:
        return [
            (a.action, a.detail)
            for a in db.scalars(
                select(AuditRecord)
                .where(AuditRecord.action.like("dhcp.%"))
                .order_by(AuditRecord.id)
            )
        ]


# --- R6.2: pools ---------------------------------------------------------------------------------


def test_r6_2_api_create_list_and_counts(api):
    client, _ = _admin(api)
    created = _pool(client, domain="Lab.Local.")
    assert created.status_code == 201
    body = created.json()
    assert (
        body["domain"],
        body["dns_servers"],
        body["reservation_count"],
        body["active_lease_count"],
    ) == ("lab.local", ["192.168.50.1"], 0, 0)
    assert [p["name"] for p in client.get(f"{BASE}/pools").json()] == ["lab-clients"]


def test_r6_2_api_errors_are_actionable(api):
    client, _ = _admin(api)
    _pool(client)
    overlap = _pool(
        client,
        name="other",
        subnet="192.168.50.128/25",
        range_start="192.168.50.200",
        range_end="192.168.50.210",
        gateway="192.168.50.129",
    )
    bad_gateway = _pool(
        client,
        name="x",
        subnet="10.0.0.0/24",
        range_start="10.0.0.10",
        range_end="10.0.0.20",
        gateway="10.0.0.15",
    )
    assert overlap.status_code == 409 and "overlaps" in overlap.json()["detail"]
    assert bad_gateway.status_code == 422 and "gateway" in bad_gateway.json()["detail"]


def test_r6_2_api_patch_revalidates_and_rejects_null(api):
    client, _ = _admin(api)
    pool_id = _pool(client).json()["id"]
    ok = client.patch(
        f"{BASE}/pools/{pool_id}", json={"lease_seconds": 600, "dns_servers": ["8.8.8.8"]}
    )
    assert ok.status_code == 200 and (ok.json()["lease_seconds"], ok.json()["dns_servers"]) == (
        600,
        ["8.8.8.8"],
    )
    assert (
        client.patch(f"{BASE}/pools/{pool_id}", json={"range_start": "192.168.50.1"}).status_code
        == 422
    )
    assert client.patch(f"{BASE}/pools/{pool_id}", json={"domain": None}).status_code == 422


def test_r6_2_deleting_a_pool_drops_its_leases_and_reservations_explicitly(api):
    """Checkpoint B: the counts are visible before deletion and recorded in the audit."""
    client, factory = _admin(api)
    pool_id = _pool(client).json()["id"]
    client.post(
        f"{BASE}/pools/{pool_id}/reservations",
        json={"mac": "aa:bb:cc:dd:ee:07", "ip": "192.168.50.10"},
    )
    _discover_and_bind(factory, 1)
    _discover_and_bind(factory, 2)
    listed = client.get(f"{BASE}/pools").json()[0]
    assert (listed["active_lease_count"], listed["reservation_count"]) == (2, 1)

    assert client.delete(f"{BASE}/pools/{pool_id}").status_code == 204
    with factory() as db:
        assert db.scalar(select(DhcpLease)) is None and db.scalar(select(DhcpReservation)) is None
    assert ("dhcp.pool.delete", "Pool 'lab-clients' (2 active leases, 1 reservations)") in _audit(
        factory
    )


# --- R6.3: reservations --------------------------------------------------------------------------


def test_r6_3_api_reservations_create_list_delete(api):
    client, _ = _admin(api)
    pool_id = _pool(client).json()["id"]
    created = client.post(
        f"{BASE}/pools/{pool_id}/reservations",
        json={"mac": "AA-BB-CC-DD-EE-07", "ip": "192.168.50.10", "hostname": "printer"},
    )
    assert created.status_code == 201
    assert (created.json()["mac"], created.json()["hostname"]) == ("aa:bb:cc:dd:ee:07", "printer")
    duplicate = client.post(
        f"{BASE}/pools/{pool_id}/reservations",
        json={"mac": "aa:bb:cc:dd:ee:07", "ip": "192.168.50.11"},
    )
    bad_mac = client.post(
        f"{BASE}/pools/{pool_id}/reservations", json={"mac": "nope", "ip": "192.168.50.12"}
    )
    assert duplicate.status_code == 409 and bad_mac.status_code == 422
    assert [r["ip"] for r in client.get(f"{BASE}/pools/{pool_id}/reservations").json()] == [
        "192.168.50.10"
    ]
    assert client.delete(f"{BASE}/reservations/{created.json()['id']}").status_code == 204
    assert client.get(f"{BASE}/pools/{pool_id}/reservations").json() == []


# --- R6.4: lease display and release -------------------------------------------------------------


def test_r6_4_active_leases_are_listed_with_details(api):
    client, factory = _admin(api)
    pool_id = _pool(client).json()["id"]
    ip = _discover_and_bind(factory, 1)
    leases = client.get(f"{BASE}/leases").json()
    assert [
        (lease["mac"], lease["ip"], lease["state"], lease["pool_name"]) for lease in leases
    ] == [("aa:bb:cc:dd:ee:01", ip, "bound", "lab-clients")]
    assert leases[0]["expires_at"]
    assert client.get(f"{BASE}/leases", params={"pool_id": pool_id}).json() == leases
    assert client.get(f"{BASE}/leases", params={"pool_id": pool_id + 1}).json() == []


def test_r6_4_expired_leases_are_not_listed(api):
    client, factory = _admin(api)
    _pool(client)
    _discover_and_bind(factory, 1)
    with factory() as db:
        db.query(DhcpLease).update({DhcpLease.expires_at: DhcpLease.updated_at})  # already expired
        db.commit()
    assert client.get(f"{BASE}/leases").json() == []


def test_r6_6_release_via_api_frees_the_address_for_the_allocator(api):
    """Checkpoint C: release through REST, then a different client is offered that address."""
    client, factory = _admin(api)
    _pool(client)
    ip = _discover_and_bind(factory, 1)
    lease_id = client.get(f"{BASE}/leases").json()[0]["id"]

    assert client.delete(f"{BASE}/leases/{lease_id}").status_code == 204
    assert client.get(f"{BASE}/leases").json() == []
    with factory() as db:
        offer = Allocator(db, "192.168.50.1").handle(
            DhcpMessage(
                op=BOOTREQUEST,
                xid=9,
                chaddr=bytes.fromhex("aabbccddee09"),
                flags=BROADCAST_FLAG,
                options={53: bytes([MessageType.DISCOVER])},
            )
        )
    assert offer.yiaddr == ipaddress.IPv4Address(ip)
    assert ("dhcp.lease.release", f"Released {ip} from aa:bb:cc:dd:ee:01") in _audit(factory)


def test_r6_4_unknown_ids_are_404_with_guidance(api):
    client, _ = _admin(api)
    for response in (
        client.delete(f"{BASE}/leases/999"),
        client.delete(f"{BASE}/pools/999"),
        client.delete(f"{BASE}/reservations/999"),
        client.post(
            f"{BASE}/pools/999/reservations", json={"mac": "aa:bb:cc:dd:ee:01", "ip": "10.0.0.5"}
        ),
    ):
        assert response.status_code == 404 and "Refresh" in response.json()["detail"]


def test_r4_4_dhcp_changes_are_audited(api):
    client, factory = _admin(api)
    pool_id = _pool(client).json()["id"]
    reservation_id = client.post(
        f"{BASE}/pools/{pool_id}/reservations",
        json={"mac": "aa:bb:cc:dd:ee:07", "ip": "192.168.50.10"},
    ).json()["id"]
    client.patch(f"{BASE}/pools/{pool_id}", json={"lease_seconds": 600})
    client.delete(f"{BASE}/reservations/{reservation_id}")
    assert [action for action, _ in _audit(factory)] == [
        "dhcp.pool.create",
        "dhcp.reservation.create",
        "dhcp.pool.update",
        "dhcp.reservation.delete",
    ]


def test_r7_2_viewer_can_read_dhcp_but_not_change_it(api):
    client, factory = _admin(api)
    _pool(client)
    sign_in(client, factory, "vera", "viewer")
    assert client.get(f"{BASE}/pools").status_code == 200
    assert client.get(f"{BASE}/leases").status_code == 200
    assert _pool(client, name="other", subnet="10.0.0.0/24").status_code == 403
