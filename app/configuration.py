import json
import os
from typing import Protocol

from netmiko import ConnectHandler
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AuditRecord, ConfigVersion, Device


class DeviceCredentials(Protocol):
    username: str
    password: str
    secret: str | None


class CredentialLookupError(RuntimeError):
    pass


class EnvironmentCredentials:
    def get(self, device: Device) -> dict[str, str]:
        raw = os.getenv("NETMGR_DEVICE_CREDENTIALS_JSON", "{}")
        try:
            configured = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CredentialLookupError(
                "Device credentials environment value is not valid JSON"
            ) from exc

        if not isinstance(configured, dict):
            raise CredentialLookupError("Device credentials must be a JSON object")
        credentials = configured.get(device.name)
        if (
            not isinstance(credentials, dict)
            or not credentials.get("username")
            or not credentials.get("password")
        ):
            raise CredentialLookupError(
                f"No username/password configured for device '{device.name}'"
            )
        result = {
            "device_type": device.platform,
            "host": device.management_ip,
            "port": device.ssh_port,
            "username": str(credentials["username"]),
            "password": str(credentials["password"]),
        }
        if credentials.get("secret"):
            result["secret"] = str(credentials["secret"])
        return result


class NetworkDeviceConnector(Protocol):
    def retrieve(self, device: Device) -> str: ...

    def push(self, device: Device, configuration: str) -> None: ...


class NetmikoConnector:
    def __init__(self, credentials: EnvironmentCredentials | None = None) -> None:
        self.credentials = credentials or EnvironmentCredentials()

    def _run(self, device: Device, operation: str, configuration: str | None = None) -> str:
        connection = ConnectHandler(**self.credentials.get(device))
        try:
            if getattr(connection, "secret", None):
                connection.enable()
            if operation == "retrieve":
                return connection.send_command("show running-config")
            if configuration is None:
                raise ValueError("A configuration snippet is required for a push")
            connection.send_config_set(configuration.splitlines())
            return ""
        finally:
            connection.disconnect()

    def retrieve(self, device: Device) -> str:
        return self._run(device, "retrieve")

    def push(self, device: Device, configuration: str) -> None:
        self._run(device, "push", configuration)


def save_config_version(
    session: Session,
    device_id: int,
    configuration: str,
    source: str,
    operator: str,
) -> ConfigVersion:
    latest = session.scalar(
        select(func.max(ConfigVersion.version)).where(ConfigVersion.device_id == device_id)
    )
    record = ConfigVersion(
        device_id=device_id,
        version=(latest or 0) + 1,
        configuration=configuration,
        source=source,
        operator=operator,
    )
    session.add(record)
    session.flush()
    return record


def record_audit_event(
    session: Session,
    actor: str,
    action: str,
    outcome: str,
    device_name: str | None = None,
    detail: str = "",
) -> AuditRecord:
    record = AuditRecord(
        actor=actor,
        action=action,
        outcome=outcome,
        device_name=device_name,
        detail=detail,
    )
    session.add(record)
    session.flush()
    return record
