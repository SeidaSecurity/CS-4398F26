# Requirements Traceability Matrix

Every SRS requirement maps to the code that implements it, the unit test that verifies it, and the
acceptance test that validates it. Update the row in the same PR that changes the behavior.

**Status key:** ✅ done and tested · 🟡 partial · ❌ not started · ⏸ deferred (Minimal priority)

Baseline audit: 2026-11-17, branch `B_trackStart` @ `632ae38`: 23 unit tests pass, 80% line coverage.
After MoT session P-002 (same day): 55 tests pass, 86% coverage, ruff 0, mypy 0.

## 4.1 Device Inventory (Track A) — Essential

| ID | Pri | Status | Implementation | Unit test | Acceptance | Gap / note |
|---|---|---|---|---|---|---|
| R1.1 Add device | E | 🟡 | `app/main.py` `create_device` | `test_api.py::test_device_create_and_duplicate_conflict` | AT-01 | Credentials are not captured in the add form (they come from an env var) |
| R1.2 Edit/remove | E | ✅ | `update_device`, `delete_device`, `schemas.PartialUpdate` | `test_device_patch_then_delete`, `test_r1_2_patch_rejects_explicit_null` | AT-01 | — |
| R1.3 Connection test | E | ❌ | — | — | AT-01 | No test connection before saving; no "save anyway" path |
| R1.4 Credential protection | E | 🟡 | `app/configuration.py` `EnvironmentCredentials` | — | — | Never returned to the browser ✔, but stored in plaintext in an env var, not encrypted |
| R1.5 Device grouping | D | ❌ | — | — | — | Needed for "device group" push (4.3.4 step 1) |
| R1.6 Discovery | M | ⏸ | — | — | — | — |

## 4.2 Monitoring and Dashboard (Track A) — Essential

| ID | Pri | Status | Implementation | Unit test | Acceptance | Gap / note |
|---|---|---|---|---|---|---|
| R2.1 Recurring poll | E | ✅ | `main.py` `poll_interval_seconds`, `_run_monitoring`, `poller.poll_all` | `test_r2_1_poll_interval_defaults_to_60_seconds` | AT-02 | Default fixed to 60 s (P-002) |
| R2.2 Reachability state | E | ✅ | `poller.poll_device`, `GET /monitoring/status` | `test_poller_failure_and_recovery` | AT-02 | — |
| R2.3 Metric collection | E | 🟡 | `app/probes.py` | — (probes 27% covered) | AT-02 | Memory not collected; no unit tests for SNMP parsing/counter math |
| R2.4 Dashboard | E | ✅ | `web/src/pages/Network.tsx` | — | AT-02 | Check "alerting devices sorted to top" (3.1.2) |
| R2.5 Alerting | E | 🟡 | `poller.poll_device` | `test_poller_failure_and_recovery` | AT-03 | Two-failure alert ✔; **metric-threshold alerts missing** |
| R2.6 Historical graphs | D | ✅ | `monitoring.py` metrics, `TimeSeries.tsx` | `test_monitoring_response_shapes_after_poll`, `test_invalid_metrics_window` | AT-02 | — |
| R2.7 Metric retention | D | ❌ | — | — | — | — |

## 4.3 Remote Configuration (Track B) — Essential

| ID | Pri | Status | Implementation | Unit test | Acceptance | Gap / note |
|---|---|---|---|---|---|---|
| R3.1 Push | E | ✅ | `ConfigurationService.push`, `NetmikoConnector.push` | `test_push_saves_versions_and_continues_after_device_failure` | AT-04 | Push by group not possible until R1.5 |
| R3.2 Retrieval | E | ✅ | `ConfigurationService.retrieve`; pre-push capture | `test_push_saves_versions_*`, `test_r3_2_retrieve_failure_returns_actionable_502_and_is_audited` | AT-04 | — |
| R3.3 Version history | E | ✅ | `save_config_version`; operator = logged-in user (`auth.current_user`) | `test_r3_3_identity_comes_from_the_session_not_a_supplied_operator` | AT-05 | Caller-supplied `operator` removed (ADR-0005) |
| R3.4 Version comparison | E | ✅ | `web/src/lib/diff.ts`, `History.tsx` | — (no diff tests) | AT-05 | Diff is computed in the front end; add unit tests or move to the API |
| R3.5 Independent failure | E | ✅ | `ConfigurationService._apply_change`, `configuration.DeviceError` hierarchy, `find_rejection` | `test_push_saves_versions_*`, `test_r3_5_unreachable_*`, `test_r3_5_failed_read_back_*`, `test_configuration.py` (classification) | AT-04 | Statuses: succeeded / unverified / rejected / unreachable / credentials / not_found / failed (P-002) |
| R3.6 Rollback | D | ✅ | `ConfigurationService.rollback` | `test_restore_*` (3 tests) | AT-05 | Replays the config; leaves in place any lines added later (see contracts.md) |
| R3.7 Templates | D | ✅ | `config_templates.py`, template routes | `test_config_templates.py`, `test_configuration_template_*` | AT-04 | — |

## 4.4 Centralized Logging (Track B) — Essential

| ID | Pri | Status | Implementation | Unit test | Acceptance | Gap / note |
|---|---|---|---|---|---|---|
| R4.1 UDP+TCP 514 | E | ✅ | `syslog.SyslogReceivers` | `test_udp_and_tcp_receivers_forward_messages` | AT-06 | — |
| R4.2 Parsing | E | ✅ | `syslog.parse_syslog`, `CISCO_IOS`, `_cisco_timestamp` | `test_parse_*`, `test_preserve_*`, `test_r4_2_*` (real IOSv samples from the lab) | AT-06 | Lab found Cisco IOS messages stored unparsed (2026-11-19); fixed the same day. Re-verify on the lab |
| R4.3 Search/filter | E | ✅ | `syslog.list_logs`, `escape_like`; sender-IP source fallback | `test_log_search_filters_records`, `test_r4_3_*` | AT-06 | Source is the hostname, or the sender IP when the message names none; still not linked to a device record |
| R4.4 Audit log | E | 🟡 | `record_audit_event`; auth events in `auth_routes.py` and `auth.enforce_access` | push/restore tests, `test_r4_4_template_changes_are_audited`, `test_r4_4_duplicate_template_name_is_not_audited`, `test_r4_4_logins_are_audited` | AT-07 | Logins, logouts and refusals now audited; account changes pending (auth increment 6) |
| R4.5 Retention | D | ❌ | — | — | — | — |
| R4.6 Export | M | ⏸ | — | — | — | — |

## 4.5 DNS (Track C) — Essential

| ID | Pri | Status | Implementation | Unit test | Acceptance | Gap / note |
|---|---|---|---|---|---|---|
| R5.1 Authoritative A/AAAA/PTR/CNAME | E | ❌ | — | — | AT-08 | Not in repository |
| R5.2 Zone/record management | E | ❌ | — | — | AT-08 | Services screen missing |
| R5.3 Negative response | E | ❌ | — | — | AT-08 | — |
| R5.4 Forwarding | D | ❌ | — | — | — | — |
| R5.5 Caching | D | ❌ | — | — | — | — |
| R5.6 Lease registration | D | ❌ | — | — | — | — |

## 4.6 DHCP (Track C) — Essential

| ID | Pri | Status | Implementation | Unit test | Acceptance | Gap / note |
|---|---|---|---|---|---|---|
| R6.1 DORA | E | ❌ | — | — | AT-09 | Not in repository |
| R6.2 Pools | E | ❌ | — | — | AT-09 | — |
| R6.3 Reservations | E | ❌ | — | — | AT-09 | — |
| R6.4 Lease display | E | ❌ | — | — | AT-09 | — |
| R6.5 Lease persistence | E | ❌ | — | — | AT-09 | — |
| R6.6 Expiry/release | E | ❌ | — | — | — | — |
| R6.7 Exhaustion log | D | ❌ | — | — | — | — |

## 4.7 Authentication and Access Control (Track A) — Essential

| ID | Pri | Status | Implementation | Unit test | Acceptance | Gap / note |
|---|---|---|---|---|---|---|
| R7.1 Auth required | E | ✅ | `auth.enforce_access` (app-wide), `auth.current_user`, `auth_routes.py` | `test_access_policy.py` (walks all OpenAPI operations), `test_auth_api.py::test_r7_1_*`, `test_auth.py::test_r7_1_*` | AT-10 | Back end done; Login screen pending (auth increment 7) |
| R7.2 Role enforcement | E | ✅ | `auth.enforce_access`: viewer gets 403 on every non-GET request, audited | `test_r7_2_every_write_route_rejects_a_viewer`, `test_r7_2_viewer_refusal_changes_nothing_and_is_audited` | AT-10 | UI hiding of write controls pending (auth increment 7) |
| R7.3 Password storage | E | ✅ | `app/auth.py` (`hash_password`, `validate_password`), `app/common_passwords.py` | `test_auth.py::test_r7_3_*` (length boundaries 7/8/64/65, common list, username, salt) | AT-10 | argon2id hashes; NIST 800-63B rules |
| R7.4 Account management | E | 🟡 | `auth.create_user`, `auth.bootstrap_admin`, startup hook in `main.py` | `test_r7_4_bootstrap_*`, `test_r7_3_create_user_*` | AT-10 | First admin from env done; account-management API pending (auth increment 6) |
| R7.5 Session expiry | D | ❌ | — | — | — | — |

## 4.8 DPI (Track C) — Minimal: R8.1–R8.5 ⏸ deferred (start only after M2)

## Non-functional

| ID | Status | Evidence / gap |
|---|---|---|
| NFR-1 Dashboard 50 devices < 3 s | ❌ not measured | Needs a seeded 50-device load test |
| NFR-2 DHCP < 500 ms @ 20 clients | ❌ | Depends on R6 |
| NFR-3 DNS < 50 ms | ❌ | Depends on R5 |
| NFR-4 1,000 logs/min, no loss | ❌ not measured | Script synthetic syslog load; count stored rows |
| NFR-5 Salted password hashes | ✅ | argon2id with a random salt per hash (`test_r7_3_hash_is_salted_and_not_the_password`) |
| NFR-6 Credentials encrypted, key outside DB | ❌ | Env-var plaintext today |
| NFR-7 HTTPS | ❌ | Plain HTTP on :8000 |
| NFR-8 Audit not modifiable via UI | ✅ | Only `GET /api/v1/audit` exists; no update/delete route |
| 5.3.2 ≥70% coverage, CI on every PR | 🟡 | 86% locally; CI workflow in `.github/workflows/ci.yml` (enable branch protection on `main` to finish) |
| 5.3.3 Actionable error messages | 🟡 | Config retrieve/push/rollback fixed (P-002, `test_5_3_3_*`); other screens not yet reviewed |
| 5.3.4 Single Docker Compose deploy | 🟡 | Compose exists; web UI not included in it |

## Summary

| Area | Essential reqs | Done | Partial | Missing |
|---|---|---|---|---|
| 4.1–4.4 (A, B) | 18 | 11 | 6 | 1 |
| 4.5–4.6 (C) | 9 | 0 | 0 | 9 |
| 4.7 (A) | 4 | 0 | 0 | 4 |
