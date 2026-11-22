# ADR-0008: Encrypted device credentials (supersedes ADR-0002)

- **Status:** Accepted (2026-11-21). Supersedes [ADR-0002](0002-device-credentials-from-environment.md).
- **Requirements:** R1.1, R1.4, NFR-6

## Context
ADR-0002 was an interim measure: credentials were read in plaintext from
`NETMGR_DEVICE_CREDENTIALS_JSON`, keyed by device name, so they could not be entered with the
device (R1.1) and were not encrypted at rest (NFR-6).

## Decision
1. **Storage:** a new table `device_credentials` (one row per device; deleted with it) holds the
   username and **Fernet ciphertext** of the password and optional enable secret. Fernet is
   AES-128-CBC with HMAC-SHA256 authentication (`cryptography`, already a dependency through
   paramiko). No column was added to `devices`, so existing databases need no migration.
2. **Key outside the database (NFR-6):** `NETMGR_SECRET_KEY` comes from the environment
   (`.env.lab`, or a Docker secret in production). It's generated with
   `Fernet.generate_key()`.
3. **Write-only API (R1.4):** device create/update accept `username`, `password`, `secret`. Responses
   contain only `has_credentials`. A test walks every device-related response, the audit log and
   the error responses, and fails if the password, the secret, or the ciphertext appears.
4. **Failure behaviour:**
   - No key when saving credentials → **503**, saying how to generate one; nothing is saved.
   - Blank or partial credentials → **422**.
   - A key that no longer matches when connecting → the push/retrieve status `credentials`, with
     "re-enter the device's credentials".
   - There is **never** a plaintext fallback for a device that has stored credentials.
5. **Lookup order:** stored credentials first, then the ADR-0002 environment JSON. Existing lab
   devices keep working until they're given stored credentials.

## Consequences
- Losing or changing `NETMGR_SECRET_KEY` makes stored credentials unreadable. Re-entering them is
  the recovery, which is the intended property of a key held outside the database.
- Updating only a password keeps the stored enable secret; deleting the device deletes its
  credentials.
- The environment-JSON fallback can be removed once every device has stored credentials.
