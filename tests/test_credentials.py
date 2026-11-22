"""Encrypted device credential store (R1.4, NFR-6).

Checkpoint B: ciphertext at rest, clear key errors.
"""

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import credentials
from app.configuration import DeviceCredentialError
from app.database import Base
from app.models import Device, DeviceCredential

PASSWORD = "S3cr3t-Pass-XYZ"
SECRET = "En4ble-Secret-QRS"


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as session:
        yield session
    engine.dispose()


@pytest.fixture
def key(monkeypatch):
    value = Fernet.generate_key().decode()
    monkeypatch.setenv("NETMGR_SECRET_KEY", value)
    return value


@pytest.fixture
def device(db):
    device = Device(name="ios-lab-1", management_ip="192.0.2.10")
    db.add(device)
    db.flush()
    return device


def test_r1_4_database_holds_only_ciphertext(db, key, device):
    credentials.store_credentials(db, device, "lab", PASSWORD, SECRET)
    db.commit()
    row = db.scalar(select(DeviceCredential))
    assert row.username == "lab"
    for stored, plain in ((row.password_ciphertext, PASSWORD), (row.secret_ciphertext, SECRET)):
        assert plain not in stored
        assert stored.startswith("gAAAA")  # Fernet token
    assert device.has_credentials is True


def test_r1_4_round_trip_and_replace(db, key, device):
    credentials.store_credentials(db, device, "lab", PASSWORD, SECRET)
    assert credentials.load_credentials(device) == {
        "username": "lab",
        "password": PASSWORD,
        "secret": SECRET,
    }
    credentials.store_credentials(
        db, device, "admin2", "Another-Pass-1"
    )  # replaces, secret cleared
    assert credentials.load_credentials(device) == {
        "username": "admin2",
        "password": "Another-Pass-1",
    }
    assert db.query(DeviceCredential).count() == 1


def test_r1_4_device_without_stored_credentials(db, device):
    assert device.has_credentials is False
    assert credentials.load_credentials(device) is None


def test_r1_4_missing_key_refuses_to_store(db, device, monkeypatch):
    monkeypatch.delenv("NETMGR_SECRET_KEY", raising=False)
    with pytest.raises(credentials.CredentialKeyError, match="NETMGR_SECRET_KEY"):
        credentials.store_credentials(db, device, "lab", PASSWORD)
    assert db.query(DeviceCredential).count() == 0


def test_r1_4_malformed_key_is_reported_with_the_fix(db, device, monkeypatch):
    monkeypatch.setenv("NETMGR_SECRET_KEY", "not-a-fernet-key")
    with pytest.raises(credentials.CredentialKeyError, match="generate"):
        credentials.store_credentials(db, device, "lab", PASSWORD)


def test_r1_4_wrong_key_fails_clearly_without_plaintext(db, device, monkeypatch):
    monkeypatch.setenv("NETMGR_SECRET_KEY", Fernet.generate_key().decode())
    credentials.store_credentials(db, device, "lab", PASSWORD)
    monkeypatch.setenv("NETMGR_SECRET_KEY", Fernet.generate_key().decode())  # key changed
    with pytest.raises(DeviceCredentialError) as caught:
        credentials.load_credentials(device)
    message = str(caught.value)
    assert "can't be decrypted" in message and "ios-lab-1" in message
    assert PASSWORD not in message


def test_r1_4_missing_key_when_loading_is_a_credential_error(db, key, device, monkeypatch):
    credentials.store_credentials(db, device, "lab", PASSWORD)
    monkeypatch.delenv("NETMGR_SECRET_KEY")
    with pytest.raises(DeviceCredentialError, match="NETMGR_SECRET_KEY"):
        credentials.load_credentials(device)


@pytest.mark.parametrize(
    ("username", "password"), [("", PASSWORD), ("lab", ""), ("x" * 121, PASSWORD)]
)
def test_r1_4_blank_or_oversized_values_are_rejected(db, key, device, username, password):
    with pytest.raises(credentials.CredentialValidationError):
        credentials.store_credentials(db, device, username, password)


def test_r1_4_credentials_are_deleted_with_the_device(db, key, device):
    credentials.store_credentials(db, device, "lab", PASSWORD)
    db.commit()
    db.delete(device)
    db.commit()
    assert db.query(DeviceCredential).count() == 0
