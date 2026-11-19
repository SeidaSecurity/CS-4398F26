"""Unit tests for the device boundary: credential lookup and Netmiko error classification.

ConnectHandler is replaced with a fake, so no SSH connection is made (SRS 8.3).
"""

import json

import pytest
from netmiko import NetmikoAuthenticationException, NetmikoTimeoutException, ReadTimeout

import app.configuration as configuration
from app.configuration import (
    CredentialLookupError,
    DeviceCredentialError,
    DeviceRejectedError,
    DeviceUnreachableError,
    EnvironmentCredentials,
    NetmikoConnector,
    find_rejection,
)
from app.models import Device

DEVICE = Device(
    id=1, name="ios-lab-1", management_ip="192.0.2.10", platform="cisco_ios", ssh_port=22
)
INVALID = "% Invalid input detected at '^' marker."
CREDS = {"ios-lab-1": {"username": "lab", "password": "pw"}}


@pytest.fixture
def credentials(monkeypatch):
    monkeypatch.setenv("NETMGR_DEVICE_CREDENTIALS_JSON", json.dumps(CREDS))


class FakeConnection:
    def __init__(self, config_output="", send_error=None, secret=None):
        self.config_output = config_output
        self.send_error = send_error
        self.secret = secret
        self.enabled = False
        self.disconnected = False
        self.sent: list[str] = []

    def enable(self):
        self.enabled = True

    def send_command(self, command):
        if self.send_error:
            raise self.send_error
        return "hostname ios-lab-1"

    def send_config_set(self, lines):
        if self.send_error:
            raise self.send_error
        self.sent = lines
        return self.config_output

    def disconnect(self):
        self.disconnected = True


def use_connection(monkeypatch, connection=None, connect_error=None):
    def connect(**kwargs):
        if connect_error:
            raise connect_error
        return connection

    monkeypatch.setattr(configuration, "ConnectHandler", connect)


# --- find_rejection: equivalence classes of IOS output -------------------------------------


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ("R1(config)#ntp server 192.0.2.1\nR1(config)#end", None),  # accepted
        (f"R1(config)#bogus\n{INVALID}", INVALID),
        ("% Incomplete command.", "% Incomplete command."),
        ("% Ambiguous command:  \"int\"", "% Ambiguous command:  \"int\""),
        ("description 100% uplink", None),  # '%' not at line start is not an error
        ("", None),
    ],
)
def test_find_rejection(output, expected):
    assert find_rejection(output) == expected


# --- EnvironmentCredentials: invalid / missing / valid ------------------------------------


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("{not json", "not valid JSON"),
        ("[]", "must be a JSON object"),
        ("{}", "Add an entry for it"),
        (json.dumps({"ios-lab-1": {"username": "lab"}}), "No username/password"),
    ],
)
def test_credentials_errors_are_actionable(monkeypatch, raw, message):
    monkeypatch.setenv("NETMGR_DEVICE_CREDENTIALS_JSON", raw)
    with pytest.raises(CredentialLookupError, match=message):
        EnvironmentCredentials().get(DEVICE)


def test_credentials_include_optional_enable_secret(monkeypatch):
    monkeypatch.setenv(
        "NETMGR_DEVICE_CREDENTIALS_JSON",
        json.dumps({"ios-lab-1": {"username": "lab", "password": "pw", "secret": "en"}}),
    )
    params = EnvironmentCredentials().get(DEVICE)
    assert params == {
        "device_type": "cisco_ios",
        "host": "192.0.2.10",
        "port": 22,
        "username": "lab",
        "password": "pw",
        "secret": "en",
    }


def test_missing_credentials_are_a_credential_error_class():
    assert issubclass(CredentialLookupError, DeviceCredentialError)
    assert DeviceCredentialError.status == "credentials"


# --- NetmikoConnector: error classification (SRS 4.3.4 5b/5c) ------------------------------


def test_push_sends_lines_and_enables_when_secret_present(monkeypatch, credentials):
    connection = FakeConnection(config_output="R1(config)#end", secret="en")
    use_connection(monkeypatch, connection)

    NetmikoConnector().push(DEVICE, "ntp server 192.0.2.1\nlogging host 192.0.2.5")

    assert connection.enabled
    assert connection.sent == ["ntp server 192.0.2.1", "logging host 192.0.2.5"]
    assert connection.disconnected


def test_ios_error_output_raises_rejected(monkeypatch, credentials):
    connection = FakeConnection(config_output="% Invalid input detected at '^' marker.")
    use_connection(monkeypatch, connection)

    with pytest.raises(DeviceRejectedError, match="ios-lab-1 rejected the configuration"):
        NetmikoConnector().push(DEVICE, "bogus command")
    assert connection.disconnected  # session closed even on failure


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (NetmikoTimeoutException("timed out"), DeviceUnreachableError),
        (ConnectionRefusedError("refused"), DeviceUnreachableError),
        (NetmikoAuthenticationException("bad auth"), DeviceCredentialError),
    ],
)
def test_connect_failures_are_classified(monkeypatch, credentials, error, expected):
    use_connection(monkeypatch, connect_error=error)
    with pytest.raises(expected) as caught:
        NetmikoConnector().retrieve(DEVICE)
    assert "ios-lab-1" in str(caught.value)
    assert "timed out" not in str(caught.value)  # raw library text is not shown


def test_mid_session_timeout_is_unreachable(monkeypatch, credentials):
    connection = FakeConnection(send_error=ReadTimeout("pattern not detected"))
    use_connection(monkeypatch, connection)

    with pytest.raises(DeviceUnreachableError, match="Lost the SSH session"):
        NetmikoConnector().retrieve(DEVICE)
    assert connection.disconnected


def test_retrieve_returns_running_config(monkeypatch, credentials):
    use_connection(monkeypatch, FakeConnection())
    assert NetmikoConnector().retrieve(DEVICE) == "hostname ios-lab-1"
