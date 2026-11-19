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

## Authentication (ADR-0005)

- Every `/api/v1/*` route requires a logged-in session, except `POST /api/v1/auth/login` and
  `POST /api/v1/auth/logout`. `/health` is public. Not logged in → `401` with
  `{"detail": "You are not logged in. Log in and try again."}`.
- `POST /api/v1/auth/login` with `{"username", "password"}` → `200` with
  `{"id", "username", "role", "created_at"}`, plus an HTTP-only, `SameSite=Lax` session cookie
  `netmgr_session` (8 h by default). Every failure → `401` with
  `{"detail": "Invalid username or password."}`.
- `POST /api/v1/auth/logout` → `204` (idempotent). `GET /api/v1/auth/me` → the current user.
- Roles: `admin` may do everything; `viewer` gets `403` on every non-GET request and on
  `/api/v1/users/*`. Refusals are audited as `access.denied` / `refused` with detail
  `"<METHOD> <path>"`. Logins are audited as `auth.login` (`succeeded`/`failed`), logouts as
  `auth.logout`.
- Clients (web UI, scripts) must send the cookie; same-origin browser requests do so
  automatically.

## REST conventions

- Prefix: `/api/v1`
- JSON request/response bodies; standard HTTP status codes and FastAPI `detail` error envelope.
- Device fields above are the provisional shared model.
- Configuration push returns one result per distinct target device; one device failure does not cancel later targets.
- `ConfigPushResult.status` (push and restore) is one of: `succeeded`; `unverified` (applied, but the resulting configuration could not be read back; `before_version` is set); `rejected` (the device refused the snippet, SRS 4.3.4 5b); `unreachable` (5c); `credentials` (missing or refused credentials); `not_found` (unknown device id); `failed` (unexpected error). `error` is an operator-facing message saying what failed and what to do; technical detail goes only to the audit record. Push/rollback logic lives in `app/config_service.py::ConfigurationService`.
- `POST /devices/{id}/config/retrieve` returns 502 with an operator-facing `detail` on device failure and writes a `configuration.retrieve` / `failed` audit record.
- Configuration versions retain full captured text, monotonically numbered per device, with `source`, `operator` (the logged-in user who caused it, R3.3), and UTC creation time.
- Configuration templates are stored in `config_templates` and exposed through `GET/POST /api/v1/configuration-templates`, `PATCH/DELETE /api/v1/configuration-templates/{template_id}`, and `POST /api/v1/configuration-templates/render`. Templates use literal `{{ variable_name }}` placeholders (ASCII letters/underscore first, then letters/digits/underscores); rendering requires a value for every distinct placeholder and rejects missing, extra, or malformed placeholders. Rendered text is previewed before the normal configuration push flow.
- `POST /api/v1/devices/{device_id}/config/versions/{version}/restore` restores a saved version, first captures the current configuration as `pre_rollback`, captures the resulting running configuration as a new `rollback` version, and audits the operation. It returns one `ConfigPushResult` and uses 404 when the device or version is missing.
- Logs expose `timestamp`, `received_at`, `source`, `facility`, `severity`, `body`, and `parsed`; raw input is retained in storage for unparsed-message troubleshooting.
- Log severity follows syslog numeric severity 0 (emergency) through 7 (debug); facility uses the syslog numeric facility.
- Accepted formats, tried in order: RFC 5424, Cisco IOS default (`<PRI>seq: host: *Mmm dd hh:mm:ss.mmm: %FAC-SEV-MNEMONIC: text`, where seq, host, `*`/`.`, year, milliseconds and timezone are optional), then RFC 3164. Anything else is stored with `parsed=false`.
- Cisco IOS: `body` keeps `%FAC-SEV-MNEMONIC: text` so mnemonics stay searchable. `timestamp` is the receive time when the router marks its clock unsynchronized (`*` or `.`); otherwise the router time, treated as UTC, with the receive year (a Dec 31 message received on Jan 1 is dated the previous year).
- `source` is the hostname in the message, or the sender's IP address when the message names none (including unparsed messages); `unknown` only if neither is available.
- The append-only audit table records operator, action, outcome (`started`, `succeeded`, `unverified`, `failed`), device (when applicable), and detail. Template create/update/delete are audited as `template.create|update|delete`. The API exposes read-only access at `GET /api/v1/audit`; The audit `actor` is always the logged-in user; no endpoint accepts a caller-supplied `operator` any more (removed 2026-11-19, ADR-0005; an `operator` sent anyway is ignored).

## Device update/delete (Track A)

- `PATCH /api/v1/devices/{device_id}` partially updates `name`, `management_ip`, `platform`, or `ssh_port`; omitted fields stay unchanged, and an explicit `null` returns 422. Returns the updated device, 404 if missing, or 409 for a duplicate name.
- `DELETE /api/v1/devices/{device_id}` returns 204 with no body (404 if missing), cascading configuration versions, poll samples, device state, alerts, interfaces, and topology links.
- Device POST/PATCH/DELETE audit successful changes, with the logged-in user as actor, as `device.create`, `device.update`, and `device.delete`; audit records are retained after deletion.

## Monitoring (Track A)

All endpoints below use GET. Shapes show example values; timestamps are UTC datetime strings. A metric `point` is `{"t":"<UTC datetime>","value":0.0}`; each metric array may be empty.

| Endpoint | JSON response shape |
|---|---|
| `/api/v1/monitoring/status` | `[{"device_id":1,"state":"up","last_poll_at":"<UTC datetime>","consecutive_failures":0}]` (`state`: `up` or `down`) |
| `/api/v1/monitoring/alerts` | `[{"id":1,"device_id":1,"message":"...","raised_at":"<UTC datetime>"}]` (unresolved alerts only) |
| `/api/v1/monitoring/topology` | `[{"a":1,"b":2}]` (device IDs) |
| `/api/v1/monitoring/devices/{device_id}/interfaces` | `[{"index":1,"name":"...","oper_status":"up","speed_mbps":1000.0}]` (`oper_status`: `up` or `down`; speed may be `null`) |
| `/api/v1/monitoring/metrics` | `{"devices_up":[point],"cpu_avg":[point],"throughput_in_bps":[point],"throughput_out_bps":[point]}` |
| `/api/v1/monitoring/devices/{device_id}/metrics` | `{"cpu":[point],"memory":[point],"throughput_in_bps":[point],"throughput_out_bps":[point]}` |

- Both metrics endpoints accept `?window=1h` (default), `24h`, or `7d`, with 1-minute, 15-minute, or 2-hour buckets respectively. Buckets without samples are omitted; null metric values are excluded. CPU/memory values are percentages; throughput is bits per second, summed across device averages for network totals. `devices_up` counts distinct devices reachable at least once in each bucket.
- Device-specific endpoints return 404 if the device is missing. Status includes devices with recorded polls.
- A device becomes down after 2 consecutive failed polls. One alert is raised per outage and resolved on the first successful poll; recovery resets the failure count.
- `MONITORING_ENABLED=true` starts background polling (default `false`); `POLL_INTERVAL_SECONDS` sets the delay between polling rounds (default `60`, per R2.1).
- `SNMP_COMMUNITY` enables SNMPv2c metrics/interfaces after a successful unprivileged ICMP probe; blank means ICMP only. SNMP failures preserve ICMP reachability. Memory is currently uncollected; throughput requires successive counter readings.

## Current limitations and follow-up decisions

- Authentication, authorization, HTTPS, secret encryption, retention jobs, and migrations are not implemented yet.
- Authentication exists (ADR-0005) but there is no TLS yet (NFR-7). Run only in an isolated lab.
- Cisco `cisco_ios` is the initial target; verify the exact IOS image and CLI behavior against the CML lab (IOSv 15.9).
- Configuration restore replays the saved configuration through the device adapter; verify restore behavior against the target IOS image, especially removal of settings added after the saved version.
- TCP syslog currently expects newline-delimited messages; confirm whether the chosen Cisco IOS image requires RFC 6587 octet-counted framing.
- The simple schema bootstrap is suitable for a clean development database; adopt Alembic migrations before shared, persistent schema evolution.
- Confirm the shared device schema/API contract with the other tracks and document any changes here.
- Topology links are not discovered yet; the topology response is empty unless rows are inserted.
- Unprivileged ICMP may need `net.ipv4.ping_group_range` configured on Linux/Docker.
