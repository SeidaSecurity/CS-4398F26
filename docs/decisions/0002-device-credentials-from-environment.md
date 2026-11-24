# ADR-0002: Device credentials from an environment variable (interim)

- **Status:** Superseded by [ADR-0008](0008-encrypted-device-credentials.md) (2026-11-21). The environment JSON remains only as a fallback for devices without stored credentials.
- **Requirements:** R1.1, R1.4, NFR-6

## Context
The SRS requires credentials to be entered with the device (R1.1), encrypted at rest with a key
held outside the database (NFR-6), and never returned to the browser (R1.4). For speed, Track B
reads plaintext credentials from `NETMGR_DEVICE_CREDENTIALS_JSON`, keyed by device name.

## Decision
Accept this only for lab development.

## Consequences / follow-up
- Renaming a device silently breaks its credential lookup.
- Planned replacement: add a `device_credentials` table holding ciphertext, encrypted with
  `cryptography.fernet` using a key from `NETMGR_SECRET_KEY` (an env var or Docker secret, never
  stored in the DB). `DeviceCreate` gains write-only `username`/`password`/`secret` fields, and
  `DeviceRead` never includes them. Add a unit test asserting that no response body contains the
  password.
