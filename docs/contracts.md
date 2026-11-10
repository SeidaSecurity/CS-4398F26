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
- Configuration templates are stored in `config_templates` and exposed through `GET/POST /api/v1/configuration-templates`, `PATCH/DELETE /api/v1/configuration-templates/{template_id}`, and `POST /api/v1/configuration-templates/render`. Templates use literal `{{ variable_name }}` placeholders (ASCII letters/underscore first, then letters/digits/underscores); rendering requires a value for every distinct placeholder and rejects missing, extra, or malformed placeholders. Rendered text is previewed before the normal configuration push flow.
- `POST /api/v1/devices/{device_id}/config/versions/{version}/restore?operator=` restores a saved version, first captures the current configuration as `pre_rollback`, captures the resulting running configuration as a new `rollback` version, and audits the operation. It returns one `ConfigPushResult` and uses 404 when the device or version is missing.
- Logs expose `timestamp`, `received_at`, `source`, `facility`, `severity`, `body`, and `parsed`; raw input is retained in storage for unparsed-message troubleshooting.
- Log severity follows syslog numeric severity 0 (emergency) through 7 (debug); facility uses the syslog numeric facility.
- The append-only audit table records operator, action, outcome, device (when applicable), and detail. The API exposes read-only access at `GET /api/v1/audit`; Track A should call the audit writer for login and account changes.

## Device update/delete (Track A)

- `PATCH /api/v1/devices/{device_id}` partially updates `name`, `management_ip`, `platform`, or `ssh_port`; omitted fields stay unchanged. Returns the updated device, 404 if missing, or 409 for a duplicate name.
- `DELETE /api/v1/devices/{device_id}` returns 204 with no body (404 if missing), cascading configuration versions, poll samples, device state, alerts, interfaces, and topology links.
- Device POST/PATCH/DELETE accept `?operator=` (default `unknown`) and audit successful changes as `device.create`, `device.update`, and `device.delete`; audit records are retained after deletion.

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
- `MONITORING_ENABLED=true` starts background polling (default `false`); `POLL_INTERVAL_SECONDS` sets the delay between polling rounds (default `30`).
- `SNMP_COMMUNITY` enables SNMPv2c metrics/interfaces after a successful unprivileged ICMP probe; blank means ICMP only. SNMP failures preserve ICMP reachability. Memory is currently uncollected; throughput requires successive counter readings.

## Current limitations and follow-up decisions

- Authentication, authorization, HTTPS, secret encryption, retention jobs, and migrations are not implemented yet.
- The API accepts operator labels but does not authenticate them. Run only in an isolated lab.
- Cisco `cisco_ios` is the initial target; verify the exact IOS image and CLI behavior against the GNS3 lab.
- Configuration restore replays the saved configuration through the device adapter; verify restore behavior against the target IOS image, especially removal of settings added after the saved version.
- TCP syslog currently expects newline-delimited messages; confirm whether the chosen Cisco IOS image requires RFC 6587 octet-counted framing.
- The simple schema bootstrap is suitable for a clean development database; adopt Alembic migrations before shared, persistent schema evolution.
- Confirm the shared device schema/API contract with the other tracks and document any changes here.
- Topology links are not discovered yet; the topology response is empty unless rows are inserted.
- Unprivileged ICMP may need `net.ipv4.ping_group_range` configured on Linux/Docker.
