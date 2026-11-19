from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator


def as_utc(value: datetime) -> datetime:
    # SQLite returns naive timestamps even for DateTime(timezone=True) columns.
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


UTCDateTime = Annotated[datetime, AfterValidator(as_utc)]


class DeviceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    management_ip: str = Field(min_length=1, max_length=255)
    platform: str = Field(default="cisco_ios", min_length=1, max_length=80)
    ssh_port: int = Field(default=22, ge=1, le=65535)


class PartialUpdate(BaseModel):
    """PATCH body: omitted fields stay unchanged; explicit nulls are rejected (NOT NULL columns)."""

    @model_validator(mode="before")
    @classmethod
    def reject_nulls(cls, data: Any) -> Any:
        if isinstance(data, dict):
            nulls = sorted(key for key, value in data.items() if value is None)
            if nulls:
                raise ValueError(f"Fields cannot be null: {', '.join(nulls)}")
        return data


class DeviceUpdate(PartialUpdate):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    management_ip: str | None = Field(default=None, min_length=1, max_length=255)
    platform: str | None = Field(default=None, min_length=1, max_length=80)
    ssh_port: int | None = Field(default=None, ge=1, le=65535)


class DeviceRead(DeviceCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime


class ConfigVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    device_id: int
    version: int
    source: str
    operator: str
    created_at: datetime


class ConfigVersionDetail(ConfigVersionRead):
    configuration: str


class ConfigTemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    configuration: str = Field(min_length=1, max_length=100_000)


class ConfigTemplateUpdate(PartialUpdate):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    configuration: str | None = Field(default=None, min_length=1, max_length=100_000)


class ConfigTemplateRead(ConfigTemplateCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


class ConfigTemplateRenderRequest(BaseModel):
    configuration: str = Field(min_length=1, max_length=100_000)
    variables: dict[str, str] = Field(default_factory=dict)


class ConfigTemplateRenderRead(BaseModel):
    configuration: str


class ConfigPushRequest(BaseModel):
    device_ids: list[int] = Field(min_length=1)
    configuration: str = Field(min_length=1)
    operator: str = Field(default="unknown", min_length=1, max_length=120)


# Per-device outcome of a push or rollback (SRS 4.3.4 step 5, R3.5):
#   succeeded   - applied and the resulting configuration was captured
#   unverified  - applied, but the resulting configuration could not be read back
#   rejected    - the device refused the configuration (5b)
#   unreachable - the device could not be reached (5c)
#   credentials - credentials are missing or were refused
#   not_found   - the device id is not in the inventory
#   failed      - unexpected error (details in the audit log)
ChangeStatus = Literal[
    "succeeded", "unverified", "rejected", "unreachable", "credentials", "not_found", "failed"
]


class ConfigPushResult(BaseModel):
    device_id: int
    status: ChangeStatus
    before_version: int | None = None
    after_version: int | None = None
    error: str | None = None


class LogRecordRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    timestamp: datetime
    received_at: datetime
    source: str
    facility: int | None
    severity: int | None
    body: str
    parsed: bool


class AuditRecordRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    occurred_at: datetime
    actor: str
    action: str
    outcome: str
    device_name: str | None
    detail: str


class DeviceStatusRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    device_id: int
    state: Literal["up", "down"]
    last_poll_at: UTCDateTime
    consecutive_failures: int


class AlertRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    device_id: int
    message: str
    raised_at: UTCDateTime


class InterfaceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    index: int
    name: str
    oper_status: Literal["up", "down"]
    speed_mbps: float | None


class TopologyLinkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    a: int
    b: int


class MetricPoint(BaseModel):
    t: UTCDateTime
    value: float


class NetworkMetrics(BaseModel):
    devices_up: list[MetricPoint]
    cpu_avg: list[MetricPoint]
    throughput_in_bps: list[MetricPoint]
    throughput_out_bps: list[MetricPoint]


class DeviceMetrics(BaseModel):
    cpu: list[MetricPoint]
    memory: list[MetricPoint]
    throughput_in_bps: list[MetricPoint]
    throughput_out_bps: list[MetricPoint]
