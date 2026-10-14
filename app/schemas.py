from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DeviceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    management_ip: str = Field(min_length=1, max_length=255)
    platform: str = Field(default="cisco_ios", min_length=1, max_length=80)
    ssh_port: int = Field(default=22, ge=1, le=65535)


class DeviceUpdate(BaseModel):
    name: str = Field(default=None, min_length=1, max_length=120)
    management_ip: str = Field(default=None, min_length=1, max_length=255)
    platform: str = Field(default=None, min_length=1, max_length=80)
    ssh_port: int = Field(default=None, ge=1, le=65535)


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


class ConfigPushRequest(BaseModel):
    device_ids: list[int] = Field(min_length=1)
    configuration: str = Field(min_length=1)
    operator: str = Field(default="unknown", min_length=1, max_length=120)


class ConfigPushResult(BaseModel):
    device_id: int
    status: str
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
