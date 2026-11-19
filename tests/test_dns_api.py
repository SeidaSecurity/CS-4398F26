"""DNS zone/record REST API (R5.2, R4.4, SRS 5.3.3)."""

from conftest import sign_in
from dnslib import RCODE, DNSRecord
from sqlalchemy import select

from app.dns.resolver import answer, load_zones
from app.models import AuditRecord

ZONES = "/api/v1/dns/zones"


def _admin(api):
    client, factory = api
    sign_in(client, factory, "ada", "admin")
    return client, factory


def _zone(client, name="lab.local", **extra):
    return client.post(ZONES, json={"name": name, **extra})


def _record(client, zone_id, name, rtype, value, **extra):
    return client.post(
        f"{ZONES}/{zone_id}/records", json={"name": name, "rtype": rtype, "value": value, **extra}
    )


def _actions(factory):
    with factory() as db:
        return [
            (a.action, a.actor, a.detail)
            for a in db.scalars(
                select(AuditRecord).where(AuditRecord.action.like("dns.%")).order_by(AuditRecord.id)
            )
        ]


def test_r5_2_create_and_list_zones(api):
    client, _ = _admin(api)
    created = _zone(client, "Lab.Local.", default_ttl=600)
    assert created.status_code == 201
    body = created.json()
    assert (body["name"], body["default_ttl"], body["record_count"]) == ("lab.local", 600, 0)
    assert [z["name"] for z in client.get(ZONES).json()] == ["lab.local"]


def test_r5_2_zone_errors_are_actionable(api):
    client, _ = _admin(api)
    _zone(client)
    duplicate = _zone(client, "LAB.local")
    invalid = _zone(client, "bad_name.local")
    assert duplicate.status_code == 409 and "already exists" in duplicate.json()["detail"]
    assert invalid.status_code == 422 and "letters, digits or hyphens" in invalid.json()["detail"]


def test_r5_2_create_list_update_delete_records(api):
    client, _ = _admin(api)
    zone_id = _zone(client).json()["id"]

    created = _record(client, zone_id, "R1", "a", "192.168.198.11")
    assert created.status_code == 201
    record = created.json()
    assert (record["name"], record["rtype"], record["fqdn"], record["ttl"]) == (
        "r1",
        "A",
        "r1.lab.local",
        None,
    )

    updated = client.patch(
        f"/api/v1/dns/records/{record['id']}", json={"value": "192.168.198.21", "ttl": 120}
    )
    assert updated.status_code == 200 and updated.json()["value"] == "192.168.198.21"
    reset = client.patch(f"/api/v1/dns/records/{record['id']}", json={"ttl": None})
    assert reset.json()["ttl"] is None  # null means "use the zone default"

    listed = client.get(f"{ZONES}/{zone_id}/records").json()
    assert [(r["name"], r["value"]) for r in listed] == [("r1", "192.168.198.21")]
    assert client.get(ZONES).json()[0]["record_count"] == 1

    assert client.delete(f"/api/v1/dns/records/{record['id']}").status_code == 204
    assert client.get(f"{ZONES}/{zone_id}/records").json() == []


def test_r5_2_record_errors_map_to_422_and_409(api):
    client, _ = _admin(api)
    zone_id = _zone(client).json()["id"]
    _record(client, zone_id, "r1", "A", "192.168.198.11")
    alias = _record(client, zone_id, "www", "CNAME", "r1.lab.local").json()

    bad_value = _record(client, zone_id, "r2", "A", "not-an-ip")
    clash = _record(client, zone_id, "r1", "CNAME", "elsewhere.lab.local")
    rename_clash = client.patch(f"/api/v1/dns/records/{alias['id']}", json={"name": "r1"})
    null_value = client.patch(f"/api/v1/dns/records/{alias['id']}", json={"value": None})

    assert bad_value.status_code == 422 and "IPv4" in bad_value.json()["detail"]
    assert clash.status_code == 409 and "CNAME" in clash.json()["detail"]
    assert rename_clash.status_code == 409
    assert null_value.status_code == 422


def test_r5_2_deleting_a_zone_removes_its_records(api):
    client, factory = _admin(api)
    zone_id = _zone(client).json()["id"]
    _record(client, zone_id, "r1", "A", "192.168.198.11")
    assert client.delete(f"{ZONES}/{zone_id}").status_code == 204
    assert client.get(ZONES).json() == []
    assert client.get(f"{ZONES}/{zone_id}/records").status_code == 404


def test_r5_2_unknown_ids_are_404_with_guidance(api):
    client, _ = _admin(api)
    for response in (
        client.patch(f"{ZONES}/999", json={"default_ttl": 300}),
        client.delete("/api/v1/dns/records/999"),
        _record(client, 999, "r1", "A", "192.168.198.11"),
    ):
        assert response.status_code == 404
        assert "Refresh" in response.json()["detail"]


def test_r4_4_dns_changes_are_audited(api):
    client, factory = _admin(api)
    zone_id = _zone(client).json()["id"]
    record_id = _record(client, zone_id, "r1", "A", "192.168.198.11").json()["id"]
    client.patch(f"/api/v1/dns/records/{record_id}", json={"value": "192.168.198.21"})
    client.patch(f"{ZONES}/{zone_id}", json={"default_ttl": 300})
    client.delete(f"/api/v1/dns/records/{record_id}")
    client.delete(f"{ZONES}/{zone_id}")
    assert _actions(factory) == [
        ("dns.zone.create", "ada", "Zone 'lab.local'"),
        ("dns.record.create", "ada", "A r1.lab.local -> 192.168.198.11"),
        ("dns.record.update", "ada", "A r1.lab.local -> 192.168.198.21"),
        ("dns.zone.update", "ada", "Zone 'lab.local': default TTL 300"),
        ("dns.record.delete", "ada", "A r1.lab.local -> 192.168.198.21"),
        ("dns.zone.delete", "ada", "Zone 'lab.local' (0 records)"),
    ]


def test_r5_1_records_created_through_the_api_are_answered(api):
    """End to end without sockets: REST create -> database -> resolver answer."""
    client, factory = _admin(api)
    zone_id = _zone(client).json()["id"]
    _record(client, zone_id, "r1", "A", "192.168.198.11")
    with factory() as db:
        reply = answer(DNSRecord.question("r1.lab.local"), load_zones(db))
    assert reply.header.rcode == RCODE.NOERROR and str(reply.rr[0].rdata) == "192.168.198.11"


def test_r7_2_viewer_can_read_dns_but_not_change_it(api):
    client, factory = _admin(api)
    _zone(client)
    sign_in(client, factory, "vera", "viewer")
    assert client.get(ZONES).status_code == 200
    assert _zone(client, "other.local").status_code == 403
