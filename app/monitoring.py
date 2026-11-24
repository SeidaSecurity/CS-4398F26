from collections import defaultdict
from datetime import UTC, datetime, timedelta
from statistics import mean
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.demo_metrics_adapter import fetch_demo_metrics, fetch_demo_state
from app.database import get_session
from app.models import (
    Alert,
    Device,
    DeviceState,
    InterfaceStatus,
    PollSample,
    TopologyLink,
    utc_now,
)
from app.schemas import (
    AlertRead,
    DeviceMetrics,
    DeviceStatusRead,
    InterfaceRead,
    MetricPoint,
    NetworkMetrics,
    TopologyLinkRead,
    as_utc,
)

from app.incident_activity_api import install_incident_route  # CS4398_INCIDENT_AGGREGATION_V5

router = APIRouter(prefix="/api/v1/monitoring")

TimeWindow = Literal["1h", "24h", "7d"]
WINDOWS = {
    "1h": (timedelta(hours=1), 60),
    "24h": (timedelta(hours=24), 15 * 60),
    "7d": (timedelta(days=7), 2 * 60 * 60),
}


@router.get("/status", response_model=list[DeviceStatusRead])
def get_status(session: Session = Depends(get_session)):
    return list(session.scalars(select(DeviceState).order_by(DeviceState.device_id)))


@router.get("/alerts", response_model=list[AlertRead])
def get_alerts(session: Session = Depends(get_session)):
    statement = (
        select(Alert)
        .where(Alert.resolved_at.is_(None))
        .order_by(Alert.raised_at.desc(), Alert.id.desc())
    )
    return list(session.scalars(statement))


@router.get("/topology", response_model=list[TopologyLinkRead])
def get_topology(session: Session = Depends(get_session)):
    return list(session.scalars(select(TopologyLink).order_by(TopologyLink.a, TopologyLink.b)))


@router.get("/devices/{device_id}/interfaces", response_model=list[InterfaceRead])
def get_interfaces(device_id: int, session: Session = Depends(get_session)):
    if session.get(Device, device_id) is None:
        raise HTTPException(status_code=404, detail="Device not found")
    statement = (
        select(InterfaceStatus)
        .where(InterfaceStatus.device_id == device_id)
        .order_by(InterfaceStatus.index)
    )
    return list(session.scalars(statement))


def sample_buckets(
    session: Session, window: TimeWindow, device_id: int | None = None
) -> dict[datetime, list[PollSample]]:
    duration, bucket_seconds = WINDOWS[window]
    now = utc_now()
    statement = select(PollSample).where(
        PollSample.polled_at >= now - duration, PollSample.polled_at <= now
    )
    if device_id is not None:
        statement = statement.where(PollSample.device_id == device_id)
    buckets = defaultdict(list)
    for sample in session.scalars(statement.order_by(PollSample.polled_at)):
        polled_at = as_utc(sample.polled_at)
        bucket = datetime.fromtimestamp(
            int(polled_at.timestamp()) // bucket_seconds * bucket_seconds, UTC
        )
        buckets[bucket].append(sample)
    return dict(sorted(buckets.items()))


def average_points(
    buckets: dict[datetime, list[PollSample]], field: str, *, network_total: bool = False
) -> list[MetricPoint]:
    """Average non-null samples; network throughput sums each device's average rate."""
    points = []
    for bucket, samples in buckets.items():
        values_by_device = defaultdict(list)
        for sample in samples:
            value = getattr(sample, field)
            if value is not None:
                values_by_device[sample.device_id].append(value)
        if values_by_device:
            value = (
                sum(mean(values) for values in values_by_device.values())
                if network_total
                else mean(value for values in values_by_device.values() for value in values)
            )
            points.append(MetricPoint(t=bucket, value=value))
    return points


@router.get("/metrics", response_model=NetworkMetrics)
def get_metrics(window: TimeWindow = "1h", session: Session = Depends(get_session)):
    demo = fetch_demo_metrics("network", window)
    if demo is not None:
        return NetworkMetrics.model_validate(demo)
    buckets = sample_buckets(session, window)
    return NetworkMetrics(
        devices_up=[
            MetricPoint(
                t=bucket, value=len({sample.device_id for sample in samples if sample.reachable})
            )
            for bucket, samples in buckets.items()
        ],
        cpu_avg=average_points(buckets, "cpu_pct"),
        throughput_in_bps=average_points(buckets, "in_bps", network_total=True),
        throughput_out_bps=average_points(buckets, "out_bps", network_total=True),
    )


@router.get("/devices/{device_id}/metrics", response_model=DeviceMetrics)
def get_device_metrics(
    device_id: int,
    window: TimeWindow = "1h",
    session: Session = Depends(get_session),
):
    if session.get(Device, device_id) is None:
        raise HTTPException(status_code=404, detail="Device not found")
    demo = fetch_demo_metrics("device", window, session.get(Device, device_id).name)
    if demo is not None:
        return DeviceMetrics.model_validate(demo)
    buckets = sample_buckets(session, window, device_id)
    return DeviceMetrics(
        cpu=average_points(buckets, "cpu_pct"),
        memory=average_points(buckets, "memory_pct"),
        throughput_in_bps=average_points(buckets, "in_bps"),
        throughput_out_bps=average_points(buckets, "out_bps"),
    )


@router.get("/demo-state")
def get_demo_state():
    return fetch_demo_state() or {"running": False, "active_warnings": [], "active_warning_count": 0, "telemetry_source": "unavailable"}

install_incident_route(router)
