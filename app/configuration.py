import json
import os
import re
from typing import Protocol

from netmiko import (
    ConnectHandler,
    NetmikoAuthenticationException,
    NetmikoTimeoutException,
    ReadTimeout,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AuditRecord, ConfigVersion, Device
from app.schemas import ChangeStatus


class DeviceCredentials(Protocol):
    username: str
    password: str
    secret: str | None


class DeviceError(RuntimeError):
    """A device operation failed; ``str(error)`` is safe to show to an operator (SRS 5.3.3)."""

    status: ChangeStatus = "failed"


class DeviceUnreachableError(DeviceError):
    """The device could not be reached over SSH (SRS 4.3.4 step 5c)."""

    status = "unreachable"


class DeviceRejectedError(DeviceError):
    """The device refused the configuration it was sent (SRS 4.3.4 step 5b)."""

    status = "rejected"


class DeviceCredentialError(DeviceError):
    """Credentials are missing, malformed, or were refused by the device."""

    status = "credentials"


class CredentialLookupError(DeviceCredentialError):
    pass


# Cisco IOS reports a rejected command with a line starting with "%".
IOS_REJECTION = re.compile(
    r"^%\s*(Invalid input|Incomplete command|Ambiguous command|Unknown command|Error).*$",
    re.IGNORECASE | re.MULTILINE,
)


def find_rejection(output: str) -> str | None:
    """Return the first IOS error line in command output, or None if the device accepted it."""
    match = IOS_REJECTION.search(output)
    return match.group(0).strip() if match else None


class EnvironmentCredentials:
    def get(self, device: Device) -> dict[str, str | int]:
        raw = os.getenv("NETMGR_DEVICE_CREDENTIALS_JSON", "{}")
        try:
            configured = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CredentialLookupError(
                "NETMGR_DEVICE_CREDENTIALS_JSON is not valid JSON. "
                "Fix the server's credential setting and try again."
            ) from exc

        if not isinstance(configured, dict):
            raise CredentialLookupError(
                "NETMGR_DEVICE_CREDENTIALS_JSON must be a JSON object keyed by device name."
            )
        credentials = configured.get(device.name)
        if (
            not isinstance(credentials, dict)
            or not credentials.get("username")
            or not credentials.get("password")
        ):
            raise CredentialLookupError(
                f"No username/password configured for device '{device.name}'. "
                "Add an entry for it to NETMGR_DEVICE_CREDENTIALS_JSON."
            )
        result: dict[str, str | int] = {
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

    def restore(self, device: Device, configuration: str) -> None: ...


class NetmikoConnector:
    def __init__(self, credentials: EnvironmentCredentials | None = None) -> None:
        self.credentials = credentials or EnvironmentCredentials()

    def _run(self, device: Device, operation: str, configuration: str | None = None) -> str:
        if operation != "retrieve" and configuration is None:
            raise ValueError("A configuration snippet is required for a push")
        address = f"{device.management_ip}:{device.ssh_port}"
        try:
            connection = ConnectHandler(**self.credentials.get(device))
        except NetmikoAuthenticationException as exc:
            raise DeviceCredentialError(
                f"{device.name} refused the SSH login. "
                "Check the username and password configured for this device."
            ) from exc
        except (NetmikoTimeoutException, OSError) as exc:
            raise DeviceUnreachableError(
                f"Could not reach {device.name} at {address}. "
                "Check that the device is powered on and SSH is enabled."
            ) from exc
        try:
            if getattr(connection, "secret", None):
                connection.enable()
            if operation == "retrieve":
                return str(connection.send_command("show running-config"))
            assert configuration is not None
            output = str(connection.send_config_set(configuration.splitlines()))
            rejection = find_rejection(output)
            if rejection:
                raise DeviceRejectedError(
                    f"{device.name} rejected the configuration: {rejection}. "
                    "Correct the snippet and push again."
                )
            return output
        except (ReadTimeout, OSError) as exc:
            raise DeviceUnreachableError(
                f"Lost the SSH session to {device.name} at {address}. "
                "Check the device and try again."
            ) from exc
        finally:
            connection.disconnect()

    def retrieve(self, device: Device) -> str:
        return self._run(device, "retrieve")

    def push(self, device: Device, configuration: str) -> None:
        self._run(device, "push", configuration)

    def restore(self, device: Device, configuration: str) -> None:
        self._run(device, "restore", configuration)


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
