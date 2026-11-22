"""Connection test before saving a device (R1.3). All device I/O is faked (SRS 8.3).

Checkpoint D: the result names the stage that failed and never contains the password.
"""

import socket

import pytest
from conftest import sign_in
from netmiko import NetmikoAuthenticationException, NetmikoTimeoutException
from sqlalchemy import select

from app.connection_test import ConnectionTester, tcp_check
from app.main import app
from app.models import AuditRecord, Device

PASSWORD = "Pw-Never-Echo-9"
FORM = {"management_ip": "192.0.2.10", "ssh_port": 22, "platform": "cisco_ios"}
CREDS = {"username": "lab", "password": PASSWORD}


def _tester(tcp_error=None, login_error=None, calls=None):
    calls = [] if calls is None else calls

    def tcp(host, port, timeout):
        calls.append(("tcp", host, port, timeout))
        if tcp_error:
            raise tcp_error

    def login(params):
        calls.append(("login", params))
        if login_error:
            raise login_error

    return ConnectionTester(tcp_check=tcp, ssh_login=login)


def test_r1_3_reachable_and_login_ok():
    calls = []
    result = _tester(calls=calls).run(**FORM, **CREDS)
    assert result.ok and result.failed_stage is None
    assert [c["stage"] for c in result.checks] == ["reachability", "login"]
    assert calls[0] == ("tcp", "192.0.2.10", 22, 3.0)
    params = calls[1][1]
    assert params["device_type"] == "cisco_ios" and params["password"] == PASSWORD
    assert params["conn_timeout"] == params["auth_timeout"] == params["banner_timeout"] == 5


def test_r1_3_without_credentials_only_reachability_is_tested():
    calls = []
    result = _tester(calls=calls).run(**FORM)
    assert result.ok and [c[0] for c in calls] == ["tcp"]
    assert "not tested" in result.message.lower()


@pytest.mark.parametrize(
    "error", [TimeoutError(), ConnectionRefusedError(), OSError("No route to host")]
)
def test_r1_3_unreachable_stops_before_login(error):
    calls = []
    result = _tester(tcp_error=error, calls=calls).run(**FORM, **CREDS)
    assert not result.ok and result.failed_stage == "reachability"
    assert "192.0.2.10:22" in result.message
    assert [c[0] for c in calls] == ["tcp"]  # no login attempted


@pytest.mark.parametrize(
    ("error", "stage", "hint"),
    [
        (NetmikoAuthenticationException(f"auth failed for {PASSWORD}"), "login", "username"),
        (NetmikoTimeoutException("banner timeout"), "login", "ssh"),
        (ValueError(f"Unsupported 'device_type' {PASSWORD}"), "login", "platform"),
        (ValueError("Failed to enter enable mode"), "enable", "enable secret"),
    ],
)
def test_r1_3_login_failures_name_the_stage_and_never_echo(error, stage, hint):
    params = {**FORM, **CREDS, "secret": "En-Secret-7"} if stage == "enable" else {**FORM, **CREDS}
    result = _tester(login_error=error).run(**params)
    assert not result.ok and result.failed_stage == stage
    assert hint in result.message.lower()
    assert PASSWORD not in result.message and "En-Secret-7" not in result.message
    assert result.checks[0]["stage"] == "reachability" and result.checks[0]["ok"] is True


def _admin(api):
    client, factory = api
    sign_in(client, factory, "ada", "admin")
    return client, factory


def test_r1_3_endpoint_reports_failure_without_saving_or_echoing(api):
    client, factory = _admin(api)
    app.state.connection_tester = _tester(login_error=NetmikoAuthenticationException(PASSWORD))
    try:
        response = client.post("/api/v1/devices/test-connection", json={**FORM, **CREDS})
    finally:
        del app.state.connection_tester
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False and body["failed_stage"] == "login"
    assert PASSWORD not in response.text
    with factory() as db:
        assert db.scalar(select(Device)) is None  # testing never saves the device
        audit = db.scalar(select(AuditRecord).where(AuditRecord.action == "device.test_connection"))
        assert audit.outcome == "failed" and PASSWORD not in (audit.detail or "")


def test_r1_3_endpoint_success(api):
    client, _ = _admin(api)
    app.state.connection_tester = _tester()
    try:
        body = client.post("/api/v1/devices/test-connection", json={**FORM, **CREDS}).json()
    finally:
        del app.state.connection_tester
    assert body["ok"] is True and len(body["checks"]) == 2


def test_r1_3_endpoint_validates_input(api):
    client, _ = _admin(api)
    response = client.post("/api/v1/devices/test-connection", json={**FORM, "ssh_port": 0})
    assert response.status_code == 422


def test_r1_3_viewer_cannot_test(api):
    client, factory = api
    sign_in(client, factory, "vic", "viewer")
    assert client.post("/api/v1/devices/test-connection", json=FORM).status_code == 403


def test_r1_3_real_tcp_check_on_loopback():
    """The real reachability stage against a local listener (no network device involved)."""
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        port = server.getsockname()[1]
        tcp_check("127.0.0.1", port, 1.0)  # open port: no error
    with pytest.raises(OSError):
        tcp_check("127.0.0.1", port, 1.0)  # listener closed: refused
