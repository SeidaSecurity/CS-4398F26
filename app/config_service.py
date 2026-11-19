"""Configuration-change controller logic (SRS 4.3), independent of HTTP.

Route handlers in ``app/main.py`` validate input, call this service, and map its results to
responses. Push and rollback share one capture -> apply -> capture -> audit sequence
(statechart: docs/design/statecharts.md section 3).
"""

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.orm import Session

from app.configuration import (
    DeviceError,
    NetworkDeviceConnector,
    record_audit_event,
    save_config_version,
)
from app.models import ConfigVersion, Device
from app.schemas import ChangeStatus

logger = logging.getLogger(__name__)

ChangeKind = Literal["push", "rollback"]


@dataclass(frozen=True)
class _ChangeSpec:
    action: str
    before_source: str
    after_source: str
    before_label: str


_SPECS: dict[ChangeKind, _ChangeSpec] = {
    "push": _ChangeSpec("configuration.push", "pre_push", "post_push", "pre-push"),
    "rollback": _ChangeSpec("configuration.rollback", "pre_rollback", "rollback", "pre-rollback"),
}


@dataclass
class ChangeResult:
    device_id: int
    status: ChangeStatus
    before_version: int | None = None
    after_version: int | None = None
    error: str | None = None


def _describe(exc: Exception, device: Device, activity: str) -> tuple[ChangeStatus, str]:
    """Map an exception to (status, operator-facing message) without leaking internals."""
    if isinstance(exc, DeviceError):
        return exc.status, str(exc)
    return "failed", (
        f"Unexpected error while {activity} on {device.name}. "
        "Details are in the audit log; retry, and report the problem if it persists."
    )


class ConfigurationService:
    def __init__(self, session: Session, connector: NetworkDeviceConnector) -> None:
        self.session = session
        self.connector = connector

    def retrieve(self, device: Device, operator: str) -> ConfigVersion:
        """Capture and store the running configuration on demand (R3.2).

        Raises ``DeviceError`` (with an operator-safe message) if the device cannot be read.
        """
        try:
            configuration = self.connector.retrieve(device)
        except Exception as exc:
            _, message = _describe(exc, device, "retrieving the configuration")
            self._audit(operator, "configuration.retrieve", "failed", device, _internal(exc))
            self.session.commit()
            if isinstance(exc, DeviceError):
                raise
            logger.exception("Configuration retrieval from %s failed", device.name)
            raise DeviceError(message) from exc
        record = save_config_version(self.session, device.id, configuration, "retrieval", operator)
        self._audit(
            operator,
            "configuration.retrieve",
            "succeeded",
            device,
            f"Saved configuration version {record.version}",
        )
        self.session.commit()
        return record

    def push(
        self, device_ids: Iterable[int], configuration: str, operator: str
    ) -> list[ChangeResult]:
        """Push to each distinct device in order; one failure never stops the rest (R3.5)."""
        results = []
        for device_id in dict.fromkeys(device_ids):
            device = self.session.get(Device, device_id)
            if device is None:
                results.append(
                    ChangeResult(
                        device_id,
                        "not_found",
                        error=(
                            f"Device {device_id} is not in the inventory. "
                            "Refresh the device list and try again."
                        ),
                    )
                )
                continue
            results.append(
                self._apply_change(
                    device, "push", operator, lambda d: self.connector.push(d, configuration)
                )
            )
        return results

    def rollback(self, device: Device, target: ConfigVersion, operator: str) -> ChangeResult:
        """Restore a stored version, saving the configuration before and after (R3.6)."""
        configuration = target.configuration
        return self._apply_change(
            device,
            "rollback",
            operator,
            lambda d: self.connector.restore(d, configuration),
            target_version=target.version,
        )

    def _apply_change(
        self,
        device: Device,
        kind: ChangeKind,
        operator: str,
        apply: Callable[[Device], None],
        target_version: int | None = None,
    ) -> ChangeResult:
        spec = _SPECS[kind]
        fail_prefix = (
            f"Failed to restore configuration version {target_version}: "
            if kind == "rollback"
            else ""
        )

        # Phase 1: capture the current configuration and commit it before touching the device,
        # so the pre-change snapshot survives any later failure.
        try:
            before = self.connector.retrieve(device)
        except Exception as exc:
            return self._fail(device, spec, operator, exc, "reading the configuration", fail_prefix)
        before_version = save_config_version(
            self.session, device.id, before, spec.before_source, operator
        ).version
        self._audit(
            operator,
            spec.action,
            "started",
            device,
            f"Saved {spec.before_label} configuration version {before_version}",
        )
        self.session.commit()

        # Phase 2: apply. Failure here means the device did not take the change.
        try:
            apply(device)
        except Exception as exc:
            result = self._fail(
                device, spec, operator, exc, "applying the configuration", fail_prefix
            )
            result.before_version = before_version
            return result

        # Phase 3: capture the result. The change is already on the device, so a failure here
        # is "unverified", not "failed" (statechart section 3).
        try:
            after = self.connector.retrieve(device)
        except Exception as exc:
            self.session.rollback()
            self._audit(
                operator,
                spec.action,
                "unverified",
                device,
                f"Change applied but read-back failed: {_internal(exc)}",
            )
            self.session.commit()
            reason = str(exc) if isinstance(exc, DeviceError) else "unexpected error"
            return ChangeResult(
                device.id,
                "unverified",
                before_version=before_version,
                error=(
                    f"The change was applied to {device.name}, but its resulting configuration "
                    f"could not be read back ({reason}). Retrieve the configuration again to "
                    "confirm the device state."
                ),
            )
        after_version = save_config_version(
            self.session, device.id, after, spec.after_source, operator
        ).version
        detail = (
            f"Restored configuration version {target_version} as version {after_version}"
            if kind == "rollback"
            else f"Configuration version {after_version} captured after push"
        )
        self._audit(operator, spec.action, "succeeded", device, detail)
        self.session.commit()
        return ChangeResult(device.id, "succeeded", before_version, after_version)

    def _fail(
        self,
        device: Device,
        spec: _ChangeSpec,
        operator: str,
        exc: Exception,
        activity: str,
        prefix: str,
    ) -> ChangeResult:
        self.session.rollback()
        status, message = _describe(exc, device, activity)
        if status == "failed":
            logger.exception("%s on %s failed unexpectedly", spec.action, device.name)
        self._audit(operator, spec.action, "failed", device, prefix + _internal(exc))
        self.session.commit()
        return ChangeResult(device.id, status, error=message)

    def _audit(
        self, operator: str, action: str, outcome: str, device: Device, detail: str
    ) -> None:
        record_audit_event(self.session, operator, action, outcome, device.name, detail)


def _internal(exc: Exception) -> str:
    """Full technical description, kept in the audit log (not shown to operators)."""
    return f"{type(exc).__name__}: {exc}"
