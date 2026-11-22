"""CPU threshold alerts (R2.5). Probes are fakes (SRS 8.3).

Rule (P-008 decision): raise at CPU >= CPU_ALERT_PERCENT, resolve when CPU drops below it.

Boundary values 89.9 / 90 / 90.1 (vv-plan). Checkpoint F: a CPU alert and the device-down alert
are independent - an open CPU alert neither suppresses a down alert nor is resolved by recovery.
"""

from datetime import timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Alert, Device, MetricAlert, utc_now
from app.poller import ProbeResult, cpu_alert_threshold, poll_device


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Device(name="r1", management_ip="192.0.2.1"))
        session.commit()
        yield session
    engine.dispose()


class Clock:
    def __init__(self):
        self.now = utc_now()

    def tick(self):
        self.now += timedelta(seconds=60)
        return self.now


def _poll(db, clock, **result):
    device = db.scalar(select(Device))
    result.setdefault("reachable", True)
    poll_device(db, device, lambda _d: ProbeResult(**result), now=clock.tick(), cpu_threshold=90)
    db.commit()


def _open(db, metric=None):
    alerts = list(db.scalars(select(Alert).where(Alert.resolved_at.is_(None))))
    marks = {m.alert_id: m.metric for m in db.scalars(select(MetricAlert))}
    return [a for a in alerts if marks.get(a.id) == metric]


@pytest.mark.parametrize(("cpu", "alerts"), [(89.9, 0), (90.0, 1), (90.1, 1)])
def test_r2_5_cpu_threshold_boundary(db, cpu, alerts):
    _poll(db, Clock(), cpu_pct=cpu)
    assert len(_open(db, "cpu")) == alerts


def test_r2_5_cpu_alert_raised_once_and_resolved_when_back_under(db):
    clock = Clock()
    for cpu in (95, 97, 99):
        _poll(db, clock, cpu_pct=cpu)
    open_cpu = _open(db, "cpu")
    assert len(open_cpu) == 1
    assert "95.0%" in open_cpu[0].message and "90%" in open_cpu[0].message
    mark = db.get(MetricAlert, open_cpu[0].id)
    assert mark.threshold == 90
    _poll(db, clock, cpu_pct=90)  # at the threshold: still alerting
    assert len(_open(db, "cpu")) == 1
    _poll(db, clock, cpu_pct=89.9)  # below: resolved
    assert _open(db, "cpu") == []


def test_r2_5_no_cpu_reading_leaves_cpu_alert_unchanged(db):
    clock = Clock()
    _poll(db, clock, cpu_pct=95)
    _poll(db, clock)  # probe returned no CPU value
    assert len(_open(db, "cpu")) == 1


def test_r2_5_checkpoint_f_down_alert_raised_while_cpu_alert_open(db):
    clock = Clock()
    _poll(db, clock, cpu_pct=95)
    _poll(db, clock, reachable=False)
    _poll(db, clock, reachable=False)
    assert len(_open(db, "cpu")) == 1
    assert len(_open(db)) == 1  # the down alert was NOT suppressed by the CPU alert
    _poll(db, clock, cpu_pct=97)  # back up, still hot
    assert _open(db) == []  # down alert resolved
    assert len(_open(db, "cpu")) == 1  # CPU alert NOT resolved by recovery


def test_r2_5_threshold_from_environment(monkeypatch):
    monkeypatch.delenv("CPU_ALERT_PERCENT", raising=False)
    assert cpu_alert_threshold() == 90.0
    monkeypatch.setenv("CPU_ALERT_PERCENT", "75")
    assert cpu_alert_threshold() == 75.0
    for bad in ("abc", "0", "101", "-5"):
        monkeypatch.setenv("CPU_ALERT_PERCENT", bad)
        assert cpu_alert_threshold() == 90.0  # invalid values fall back to the default
