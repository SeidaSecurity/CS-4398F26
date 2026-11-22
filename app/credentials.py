"""Encrypted device credentials (R1.1, R1.4, NFR-6). Decisions in ADR-0008.

Passwords and enable secrets are encrypted with Fernet (AES-128-CBC + HMAC-SHA256) using
NETMGR_SECRET_KEY from the environment; the key is never stored in the database. Nothing in
this module returns credentials to an HTTP caller - only the device connector reads them.
"""

import os

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from app.configuration import DeviceCredentialError, EnvironmentCredentials
from app.models import Device, DeviceCredential, utc_now

KEY_HELP = (
    'Generate one with: .venv\\Scripts\\python -c "from cryptography.fernet import Fernet; '
    'print(Fernet.generate_key().decode())", put it in .env.lab as NETMGR_SECRET_KEY=..., '
    "and restart."
)


class CredentialKeyError(RuntimeError):
    """NETMGR_SECRET_KEY is missing or malformed (a server configuration problem)."""


class CredentialValidationError(ValueError):
    """A credential value is blank or too long."""


def _fernet() -> Fernet:
    key = os.getenv("NETMGR_SECRET_KEY", "").strip()
    if not key:
        raise CredentialKeyError(
            "The server has no NETMGR_SECRET_KEY, so credentials can't be stored securely. "
            f"{KEY_HELP}"
        )
    try:
        return Fernet(key.encode())
    except ValueError as exc:
        raise CredentialKeyError(f"NETMGR_SECRET_KEY is not a valid key. {KEY_HELP}") from exc


def _check(value: str, what: str, maximum: int) -> str:
    if not value or not value.strip():
        raise CredentialValidationError(f"{what} is required.")
    if len(value) > maximum:
        raise CredentialValidationError(f"{what} must be at most {maximum} characters.")
    return value


def store_credentials(
    db: Session, device: Device, username: str, password: str, secret: str | None = None
) -> DeviceCredential:
    """Encrypt and store (or replace) a device's credentials."""
    _check(username, "Username", 120)
    _check(password, "Password", 256)
    if secret:
        _check(secret, "Enable secret", 256)
    fernet = _fernet()
    password_token = fernet.encrypt(password.encode()).decode()
    secret_token = fernet.encrypt(secret.encode()).decode() if secret else None
    record = device.credential
    if record is None:
        record = DeviceCredential(device_id=device.id)
        device.credential = record
    record.username = username.strip()
    record.password_ciphertext = password_token
    record.secret_ciphertext = secret_token
    record.updated_at = utc_now()
    db.flush()
    return record


def load_credentials(device: Device) -> dict[str, str] | None:
    """Decrypt a device's stored credentials, or None if it has none.

    Raises DeviceCredentialError (an operator-safe message, push status "credentials") when the
    key is missing or no longer matches. There is never a plaintext fallback.
    """
    record = device.credential
    if record is None:
        return None
    try:
        fernet = _fernet()
    except CredentialKeyError as exc:
        raise DeviceCredentialError(str(exc)) from exc
    try:
        result = {
            "username": record.username,
            "password": fernet.decrypt(record.password_ciphertext.encode()).decode(),
        }
        if record.secret_ciphertext:
            result["secret"] = fernet.decrypt(record.secret_ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise DeviceCredentialError(
            f"Stored credentials for {device.name} can't be decrypted; NETMGR_SECRET_KEY may have "
            "changed. Re-enter the device's credentials on the Devices screen."
        ) from exc
    return result


class StoredOrEnvironmentCredentials(EnvironmentCredentials):
    """Connector credential source: stored (encrypted) credentials first, then the env JSON.

    The env fallback (ADR-0002) keeps existing lab devices working until they get stored
    credentials (checkpoint C).
    """

    def get(self, device: Device) -> dict[str, str | int]:
        stored = load_credentials(device)
        if stored is None:
            return super().get(device)
        params: dict[str, str | int] = {
            "device_type": device.platform,
            "host": device.management_ip,
            "port": device.ssh_port,
            **stored,
        }
        return params
