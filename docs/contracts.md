# Initial Track B contracts (proposal)

These are implementation defaults, not team-approved shared contracts. Review the device fields and REST conventions with Tracks A/C and agree before depending on them across track boundaries.

## Device record

| Field | Type | Meaning |
|---|---|---|
| `id` | integer | Database-generated stable identifier |
| `name` | string | Unique lab/operator-facing device name |
| `management_ip` | string | SSH management address or resolvable hostname |
| `platform` | string | Netmiko device type; `cisco_ios` by default |
| `ssh_port` | integer | SSH port, default 22 |
| `created_at` | UTC datetime | Record creation time |

Credentials are deliberately outside the device table. The current lab adapter looks them up by device name in `NETMGR_DEVICE_CREDENTIALS_JSON`. A proper shared secrets manager/credential-encryption approach must be agreed before production use.

## REST conventions

- Prefix: `/api/v1`
- JSON request/response bodies; standard HTTP status codes and FastAPI `detail` error envelope.
- Device fields above are the provisional shared model.
- Configuration push returns one result per distinct target device; one device failure does not cancel later targets.
- Configuration versions retain full captured text, monotonically numbered per device, with `source`, `operator`, and UTC creation time.
- Logs expose `timestamp`, `received_at`, `source`, `facility`, `severity`, `body`, and `parsed`; raw input is retained in storage for unparsed-message troubleshooting.
- Log severity follows syslog numeric severity 0 (emergency) through 7 (debug); facility uses the syslog numeric facility.
- The append-only audit table records operator, action, outcome, device (when applicable), and detail. The API exposes read-only access at `GET /api/v1/audit`; Track A should call the audit writer for login and account changes.

## Current limitations and follow-up decisions

- Authentication, authorization, HTTPS, secret encryption, retention jobs, migrations, diff/rollback, and configuration templates are not implemented yet.
- The API accepts operator labels but does not authenticate them. Run only in an isolated lab.
- Cisco `cisco_ios` is the initial target; verify the exact IOS image and CLI behavior against the GNS3 lab.
- TCP syslog currently expects newline-delimited messages; confirm whether the chosen Cisco IOS image requires RFC 6587 octet-counted framing.
- The simple schema bootstrap is suitable for a clean development database; adopt Alembic migrations before shared, persistent schema evolution.
- Confirm the shared device schema/API contract with the other tracks and document any changes here.
