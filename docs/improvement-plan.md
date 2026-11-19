# Improvement Plan: SRS Conformance, Design, and Process

Audit of `632ae38` (2026-11-17). **Done in P-002:** #6, #7, #8, #9 (config screens), #10, #13, #15, #20. Presentations start **Nov 24**, so items are ordered by what most
affects the grade: Essential requirements first, then design principles, then process evidence.

## P0: Essential requirements that are missing (blocks M2 / the demo)

| # | Gap | Requirement | Suggested approach | Owner |
|---|---|---|---|---|
| 1 | No authentication or roles | R7.1–R7.4, NFR-5, R4.4 (logins) | `users` table (username, `argon2`/`bcrypt` hash, role, disabled). `POST /api/v1/auth/login` issues a session cookie or JWT. A FastAPI dependency `current_user` on every router, plus `require_admin` on writes. Replace the `operator` query param with `current_user.username`. Add a Login screen. Password rule: ≥ 8 chars, checked against a small breached-password list (NIST 800-63B) | A |
| 2 | No DNS service | R5.1–R5.3 | `services/dns/` with `dnslib` `BaseResolver`. Zones/records in DB tables; return the `aa` flag; NXDOMAIN with SOA for local misses. Unit-test the resolver with `dnslib` packets, no sockets | C |
| 3 | No DHCP service | R6.1–R6.6 | `services/dhcp/`: pure `LeaseAllocator` class (reservation → next free → exhausted) unit-tested without sockets, plus a thin raw-socket/scapy transport. Leases in DB (R6.5) | C |
| 4 | No connection test on add | R1.3 | `POST /api/v1/devices/test-connection` calling `connector.retrieve()` (or a TCP connect to `ssh_port`) with a timeout. UI shows the result with "Save anyway" / "Fix" | A |
| 5 | No Services screen | 3.1.6 | Zones/records, pools/reservations, and a leases table; follow `web/README.md` "Add a screen" | C |

## P1: Partial requirements and defects found in review

| # | Finding | Where | Why it matters | Fix |
|---|---|---|---|---|
| 6 ✅ | Default poll interval is 30 s | `app/main.py:69`, `.env.example:3` | R2.1 says 60 s | Change both to `60` |
| 7 ✅ | A push applied on the device but followed by a failed post-push retrieve is reported **failed** | `app/main.py` ~397 | Misreports device state; violates 4.3.4 5a | Track the phase; return `status="unverified"` once `push()` returns (implemented) |
| 8 ✅ | Outcomes do not distinguish *rejected* from *unreachable* | push/restore `except Exception` | 4.3.4 5b vs 5c | Connector raises `DeviceUnreachableError` / `DeviceRejectedError` (wrap Netmiko timeouts/auth errors and `%`-prefixed IOS output); map each to a status |
| 9 ✅ | Raw exception text sent to the UI | `app/main.py:169`, push/restore `error` | SRS 5.3.3: say what failed and what to do | Map the exception types above to friendly messages ("Could not reach 10.0.0.1:22. Check that the device is up and SSH is enabled.") and log the traceback server-side |
| 10 ✅ | Template CRUD not audited | `create/update/delete_configuration_template` | R4.4 "every configuration change" | Call `record_audit_event` in each |
| 11 | No metric-threshold alerts | `poller.poll_device` | R2.5 second clause | `thresholds` config (e.g. CPU > 90%). Raise/resolve the alert in `poll_device`; add tests at 89.9/90/90.1 |
| 12 | Memory not collected | `probes.snmp_probe` | R2.3 | Walk `hrStorageTable` (RAM rows) or the Cisco `ciscoMemoryPool` OIDs |
| 13 ✅ | Log search treats `%` and `_` as wildcards | `app/syslog.py:141` | Wrong results for searches containing those characters | Escape them and use `ilike(..., escape="\\")` |
| 14 | `create_all` runs at import time | `app/main.py:37` | Side effect on import; tests create `network_manager.db`; no migrations | Move into lifespan; adopt Alembic (SRS 7.1) before the schema changes again |
| 15 ✅ | mypy: 11 errors | `schemas.py:57-58` (`str = None` → `str \| None = None`), `database.py:14`, `configuration.py:52,73`, `syslog.py:111` | SRS 10.4 requires mypy in CI | Fix, then make the CI mypy step blocking |
| 16 | Restore replays the config but does not remove later lines | `NetmikoConnector.restore` | R3.6 "restore to a previous version" is only partly true | IOS `configure replace` (copy to flash, then replace) or NAPALM `load_replace_candidate` + `commit_config` |
| 17 | Retention not implemented | — | R2.7, R4.5 (Desirable) | Daily job deleting rows `< now - RETENTION_DAYS`; unit-test with fixed `now` |
| 18 | Web UI not in Compose; no HTTPS | `docker-compose.yml` | 5.3.4, NFR-7 | Add `web` (nginx serving `dist/` and proxying `/api`) with a self-signed cert for the lab |

## P2: Design principles (what the instructor checks for "follows design principles")

19. **Split `app/main.py` into controllers (SRP).** It is 464 lines mixing devices, config,
    templates, logs, and audit. Create `APIRouter`s: `app/api/devices.py`, `app/api/configuration.py`,
    `app/api/logs.py`, `app/api/audit.py` (as `monitoring.py` already does). `main.py` keeps only
    the lifespan and `include_router`.
20. ✅ **Extract a `ConfigurationService` class (DRY + testable controller).** Done: `app/config_service.py`. `push_configuration`
    and `restore_configuration` repeat the same capture → apply → capture → audit sequence. One
    method, `apply_change(device, text, kind: Literal["push","rollback"], operator)`, removes about
    60 duplicated lines, and gives you a "Controller class" to unit-test directly with JUnit-style
    tests (deliverable 8).
21. **Make the probe math pure.** Extract `compute_rates(previous, current) -> (in_bps, out_bps)`
    from `snmp_probe` and keep `_previous_readings` inside a `CounterCache` class. Unit-test reboot,
    counter wrap, and the first reading.
22. **Package layout vs SRS 10.1.** The SRS promises `platform/`, `config/`, `logging/`,
    `services/`. **Don't create a top-level `logging/`**: it shadows Python's stdlib `logging`.
    Either update the SRS to describe the current `app/` modules or move to
    `app/platform/`, `app/configmgmt/`, `app/syslog/`, `app/services/{dns,dhcp}/`. Whichever you
    choose, make the SRS and the code agree (record it as ADR-0003).
23. **Consistent operator identity.** Push takes `operator` in the JSON body; every other endpoint
    takes it as a query param. This goes away when #1 lands, because identity comes from the session.
24. **Diff location.** R3.4 is satisfied by `web/src/lib/diff.ts`, but SRS 6.2 says the front end
    holds no application logic. Either add unit tests (Vitest) and argue that diffing is
    presentation logic, or add `GET /devices/{id}/config/diff?a=&b=` using Python `difflib`.

## P3: Process evidence (deliverables 1, 8, 10 and the "disciplined process" criterion)

25. **CI** — `.github/workflows/ci.yml` added: ruff, pytest with a 70% coverage gate, mypy
    (advisory), and the web build. Turn on branch protection for `main` (SRS 10.1).
26. **PR template** — `.github/pull_request_template.md` added; it forces requirement IDs and the DoD checklist.
27. **Branch naming** — current branches (`B_trackStart`, `ui/web-dashboard`) don't follow
    `track-<x>/<issue>-<slug>`. Use the convention from now on so the git Network graph tells the story.
28. **Rename tests to carry requirement IDs** (`test_r3_5_push_continues_after_failure`) so the RTM
    can be checked mechanically: `pytest --collect-only -q | grep r3_5`.
29. **Prompt log** — start logging now (`docs/process/prompt-log.md`) and reconstruct the earlier
    sessions from commits.
30. **Lab artifacts** — `lab/` with the GNS3/Containerlab topology and router base configs (SRS 8.4).

## Suggested order for the next week

1. ~~#6, #10, #13, #15~~ and ~~#7, #8, #9 via #20~~: done in P-002.
2. #19: split the remaining `main.py` routes into routers. #21: make the probe math pure.
3. #1 auth (Track A) and #2/#3 DNS/DHCP core logic (Track C) in parallel.
4. Run AT-01…AT-07 on the lab and capture screenshots.
5. Build the slides from `docs/design/*` and `docs/verification/*`.
