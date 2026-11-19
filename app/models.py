from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    management_ip: Mapped[str] = mapped_column(String(255))
    platform: Mapped[str] = mapped_column(String(80), default="cisco_ios")
    ssh_port: Mapped[int] = mapped_column(Integer, default=22)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    config_versions: Mapped[list["ConfigVersion"]] = relationship(
        back_populates="device", cascade="all, delete-orphan"
    )


class ConfigVersion(Base):
    __tablename__ = "config_versions"
    __table_args__ = (UniqueConstraint("device_id", "version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)
    configuration: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(32))
    operator: Mapped[str] = mapped_column(String(120), default="unknown")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    device: Mapped[Device] = relationship(back_populates="config_versions")


class ConfigTemplate(Base):
    __tablename__ = "config_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    configuration: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class PollSample(Base):
    __tablename__ = "poll_samples"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    polled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, index=True
    )
    reachable: Mapped[bool] = mapped_column()
    rtt_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    cpu_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    memory_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    in_bps: Mapped[float | None] = mapped_column(Float, nullable=True)
    out_bps: Mapped[float | None] = mapped_column(Float, nullable=True)


class DeviceState(Base):
    __tablename__ = "device_states"
    __table_args__ = (CheckConstraint("state IN ('up', 'down')"),)

    device_id: Mapped[int] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True
    )
    state: Mapped[str] = mapped_column(String(4))
    last_poll_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"))
    message: Mapped[str] = mapped_column(Text)
    raised_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class InterfaceStatus(Base):
    __tablename__ = "interface_statuses"
    __table_args__ = (CheckConstraint("oper_status IN ('up', 'down')"),)

    device_id: Mapped[int] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True
    )
    index: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    oper_status: Mapped[str] = mapped_column(String(4))
    speed_mbps: Mapped[float | None] = mapped_column(Float, nullable=True)


class TopologyLink(Base):
    __tablename__ = "topology_links"

    a: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True)
    b: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True)


class LogRecord(Base):
    __tablename__ = "log_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    source: Mapped[str] = mapped_column(String(255), index=True)
    facility: Mapped[int | None] = mapped_column(Integer, nullable=True)
    severity: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    body: Mapped[str] = mapped_column(Text)
    raw_message: Mapped[str] = mapped_column(Text)
    parsed: Mapped[bool] = mapped_column(default=False)


class AuditRecord(Base):
    __tablename__ = "audit_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    actor: Mapped[str] = mapped_column(String(120))
    action: Mapped[str] = mapped_column(String(120), index=True)
    outcome: Mapped[str] = mapped_column(String(32))
    device_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    detail: Mapped[str] = mapped_column(Text, default="")


# --- Authentication (SRS 4.7). New tables only, so existing lab databases need no migration. ---


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("role IN ('admin', 'viewer')"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(8))
    disabled: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    # SHA-256 of the cookie token; the token itself is never stored.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
