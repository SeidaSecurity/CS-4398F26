"""Read-only time-bucketed incident data from the capstone's STORED syslog records.

Uses existing authenticated /api/v1/monitoring router; no metrics invented in browser.
"""
from datetime import UTC, datetime, timedelta

from fastapi import Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_session
from app.models import LogRecord
from app.schemas import as_utc


def incident_activity(session: Session, source: str | None = None, seconds: int = 120):
    seconds = max(30, min(seconds, 600))
    now = datetime.now(UTC)
    start = now - timedelta(seconds=seconds)
    count = 48
    bins = [{"t": (start + timedelta(seconds=seconds * i / count)).isoformat(),
             "all": 0, "warnings": 0, "errors": 0} for i in range(count)]
    statement = select(LogRecord.timestamp, LogRecord.severity).where(
        LogRecord.timestamp >= start, LogRecord.timestamp <= now)
    if source:
        statement = statement.where(LogRecord.source == source)
    for stamp, severity in session.execute(statement):
        offset = (as_utc(stamp) - start).total_seconds()
        index = max(0, min(count - 1, int(offset * count / seconds)))
        bins[index]["all"] += 1
        if severity is not None and severity <= 3:
            bins[index]["errors"] += 1
        elif severity == 4:
            bins[index]["warnings"] += 1
    return {"source": "stored_syslog", "seconds": seconds, "buckets": bins,
            "total": sum(x["all"] for x in bins),
            "error_count": sum(x["errors"] for x in bins),
            "warning_count": sum(x["warnings"] for x in bins)}


def install_incident_route(router):
    @router.get('/incident-activity')
    def get_incident_activity(
        source: str | None = None,
        seconds: int = Query(120, ge=30, le=600),
        session: Session = Depends(get_session),
    ):
        return incident_activity(session, source, seconds)
