"""Connection test for a device's unsaved form values (R1.3).

Two stages, each with a short timeout, so the operator waits at most about 18 seconds:
  1. reachability - TCP connect to the SSH port (3 s);
  2. login        - SSH login, plus `enable` when a secret is given (5 s each for connect,
                    banner and authentication). Skipped when no credentials were entered.
Messages are fixed templates: exception text (which can echo input) is never included,
so the password cannot leak into the result or the audit log (checkpoint D).
"""

import socket
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from netmiko import ConnectHandler, NetmikoAuthenticationException, NetmikoTimeoutException

TCP_TIMEOUT_SECONDS = 3.0
SSH_TIMEOUT_SECONDS = 5


def tcp_check(host: str, port: int, timeout: float) -> None:
    with socket.create_connection((host, port), timeout=timeout):
        pass


def ssh_login(params: dict[str, Any]) -> None:
    connection = ConnectHandler(**params)
    try:
        if params.get("secret"):
            connection.enable()
    finally:
        connection.disconnect()


@dataclass
class ConnectionTestResult:
    ok: bool
    failed_stage: str | None
    message: str
    checks: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class ConnectionTester:
    def __init__(
        self,
        tcp_check: Callable[[str, int, float], None] = tcp_check,
        ssh_login: Callable[[dict[str, Any]], None] = ssh_login,
    ) -> None:
        self.tcp_check = tcp_check
        self.ssh_login = ssh_login

    def run(
        self,
        management_ip: str,
        ssh_port: int,
        platform: str = "cisco_ios",
        username: str | None = None,
        password: str | None = None,
        secret: str | None = None,
    ) -> ConnectionTestResult:
        address = f"{management_ip}:{ssh_port}"
        checks: list[dict[str, Any]] = []

        def fail(stage: str, message: str) -> ConnectionTestResult:
            checks.append({"stage": stage, "ok": False, "message": message})
            return ConnectionTestResult(False, stage, message, checks)

        try:
            self.tcp_check(management_ip, ssh_port, TCP_TIMEOUT_SECONDS)
        except OSError:  # includes socket.timeout and ConnectionRefusedError
            return fail(
                "reachability",
                f"Nothing answered on {address}. Check the management IP and SSH port, and that "
                "the device is powered on with SSH enabled.",
            )
        checks.append({"stage": "reachability", "ok": True, "message": f"{address} is reachable."})

        if not (username and password):
            message = f"{address} is reachable. Login not tested: no username and password entered."
            return ConnectionTestResult(True, None, message, checks)

        params: dict[str, Any] = {
            "device_type": platform,
            "host": management_ip,
            "port": ssh_port,
            "username": username,
            "password": password,
            "conn_timeout": SSH_TIMEOUT_SECONDS,
            "auth_timeout": SSH_TIMEOUT_SECONDS,
            "banner_timeout": SSH_TIMEOUT_SECONDS,
        }
        if secret:
            params["secret"] = secret
        try:
            self.ssh_login(params)
        except NetmikoAuthenticationException:
            return fail("login", "The device refused the login. Check the username and password.")
        except (NetmikoTimeoutException, OSError, EOFError):
            return fail(
                "login",
                f"{address} accepted the connection but the SSH session did not complete. "
                "Check that this port is SSH and the device's SSH server is running.",
            )
        except ValueError as exc:
            if "device_type" in str(exc):
                return fail(
                    "login",
                    f"Platform '{platform}' isn't supported. Use a Netmiko device type such as "
                    "cisco_ios.",
                )
            return fail(
                "enable",
                "Logged in, but entering enable mode failed. Check the enable secret.",
            )
        checks.append({"stage": "login", "ok": True, "message": f"Logged in as {username}."})
        return ConnectionTestResult(True, None, "Reachable and the login succeeded.", checks)
