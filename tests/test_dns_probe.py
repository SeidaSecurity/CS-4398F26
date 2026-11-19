"""The lab probe (scripts/dns_probe.py) reports rcode, AA and timing correctly (NFR-3 tooling)."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.dns import zones
from app.dns.server import DnsService

PROBE = Path(__file__).resolve().parent.parent / "scripts" / "dns_probe.py"


@pytest.fixture
def server():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        lab = zones.create_zone(db, "lab.local")
        zones.create_record(db, lab, "r1", "A", "192.168.198.11")
        db.commit()
    service = DnsService(factory, "127.0.0.1", 0)
    service.start()
    yield service.port
    service.stop()
    engine.dispose()


def _run(*args):
    done = subprocess.run(
        [sys.executable, str(PROBE), *args], capture_output=True, text=True, timeout=30
    )
    return done.returncode, json.loads(done.stdout)


def test_nfr_3_probe_reports_authoritative_answer_and_timing(server):
    code, result = _run("r1.lab.local", "--port", str(server), "--repeat", "3")
    assert code == 0
    assert (result["rcode"], result["aa"]) == ("NOERROR", True)
    assert result["answers"] == [{"name": "r1.lab.local", "type": "A", "value": "192.168.198.11"}]
    assert 0 < result["median_ms"] <= result["max_ms"]


def test_r5_3_probe_reports_nxdomain(server):
    code, result = _run("missing.lab.local", "--port", str(server))
    assert code == 0 and (result["rcode"], result["aa"], result["answers"]) == (
        "NXDOMAIN",
        True,
        [],
    )


def test_probe_reports_an_unreachable_server_without_crashing():
    code, result = _run("r1.lab.local", "--port", "9", "--timeout", "0.5")  # nothing answers on 9
    assert code == 1 and result["ok"] is False and result["error"]
