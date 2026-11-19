# Acceptance Test Cases

Derived from the SRS Section 4 stimulus/response sequences. Run them against the live stack
(on Windows: `scriptsun-lab.ps1`; on Linux: `docker compose up` plus the live web UI) and the CML lab.
For each step, capture a screenshot of the window, or the pop-up/dialog if one appears, and save
it as `docs/acceptance/screenshots/AT-xx/step-NN.png`. Record Actual and Pass/Fail for every step.

**Run log**

| AT | Date | Tester | Build (commit) | Result |
|---|---|---|---|---|
| AT-01 | | | | |

---

## AT-01 Register, edit, and remove a device — R1.1, R1.2, (R1.3)

**Preconditions:** Logged in as an administrator (once R7 exists). Lab router `ios-lab-1` is
reachable at its management IP. Its credentials are configured.

| # | Action | Expected | Actual | P/F | Screenshot |
|---|---|---|---|---|---|
| 1 | Open **Devices** | Inventory list shown | | | step-01 |
| 2 | Select **Add device** | Add form opens | | | step-02 |
| 3 | Enter name `ios-lab-1`, IP, platform `cisco_ios`, port 22; submit | (R1.3) Connection-test result shown; device appears in list | | | step-03 |
| 4 | Add a second device with the same name | Error: "A device with that name already exists" | | | step-04 |
| 5 | Edit `ios-lab-1`: change SSH port | Updated value shown | | | step-05 |
| 6 | Delete the device | **Confirmation dialog** appears (SRS 3.1) | | | step-06 |
| 7 | Confirm | Device removed; audit shows `device.delete` | | | step-07 |

**Alternate (4.1.4 b):** Add a device with an unreachable IP. Expected: failure reason shown, with
options to "save anyway" or correct the entry. *Blocked until R1.3 is implemented.*

## AT-02 Dashboard reflects live state — R2.1, R2.2, R2.3, R2.4, R2.6

**Preconditions:** `MONITORING_ENABLED=true`, `SNMP_COMMUNITY` set, three lab routers registered.

| # | Action | Expected | Actual | P/F | Screenshot |
|---|---|---|---|---|---|
| 1 | Open **Network** (dashboard) | Every device listed with state, last poll time, alerts | | | |
| 2 | Wait one poll interval (default 60 s per R2.1) | Last-poll time advances | | | |
| 3 | Select a device | Detail with CPU, interfaces, throughput graph | | | |
| 4 | Change window to 24h / 7d | Graph re-buckets | | | |

## AT-03 Down-device alert — R2.5

**Preconditions:** The lab's "unreachable node" (powered off) is registered.

| # | Action | Expected | Actual | P/F | Screenshot |
|---|---|---|---|---|---|
| 1 | Wait one poll | Device still **up**, failures = 1 | | | |
| 2 | Wait a second poll | Device **down**, alert raised, sorted to top and visually distinct | | | |
| 3 | Power the node on; wait one poll | Device **up**, alert resolved | | | |

## AT-04 Push configuration to several devices with one failure — R3.1, R3.2, R3.5, R3.7

**Preconditions:** `ios-lab-1` and `ios-lab-2` reachable; `ios-lab-3` registered but powered off.

| # | Action | Expected | Actual | P/F | Screenshot |
|---|---|---|---|---|---|
| 1 | Open **Push** | Editor, device selector, templates | | | |
| 2 | Choose template; fill variables | Rendered preview shown | | | |
| 3 | Leave a variable empty | Error "Missing template values: …" | | | |
| 4 | Select all three devices; click **Push** | **Confirmation dialog** lists the targets and the rendered config (4.3.4 step 3) | | | |
| 5 | Confirm | Per-device summary: lab-1 ✓, lab-2 ✓, lab-3 ✗ unreachable; lab-1/2 still complete | | | |
| 6 | Open **History** for lab-1 | New `pre_push` and `post_push` versions with operator and time | | | |

## AT-05 Compare and roll back versions — R3.3, R3.4, R3.6

| # | Action | Expected | Actual | P/F | Screenshot |
|---|---|---|---|---|---|
| 1 | **History** → choose two versions | Side-by-side diff, +/− counts | | | |
| 2 | Select **Restore** on an older version | Confirmation dialog | | | |
| 3 | Confirm | Result shows new `pre_rollback` and `rollback` versions; audit entry | | | |

## AT-06 Centralized logging — R4.1, R4.2, R4.3

| # | Action | Expected | Actual | P/F | Screenshot |
|---|---|---|---|---|---|
| 1 | On the router: `logging host <app-ip>`; trigger `shut`/`no shut` on an interface | — | | | |
| 2 | Open **Logs** | New messages with severity, source, timestamp, newest first | | | |
| 3 | Filter severity = 3, source = router, last 15 min | Only matching rows | | | |
| 4 | Send a malformed line with `nc -u <app-ip> 514` | Stored and flagged unparsed (not dropped) | | | |

## AT-07 Audit trail — R4.4, NFR-8

| # | Action | Expected | Actual | P/F | Screenshot |
|---|---|---|---|---|---|
| 1 | After AT-01/04/05, open the audit view | Each change listed with actor, action, outcome, time | | | |
| 2 | Look for any edit or delete control | None exists (read-only) | | | |

## AT-08 DNS — R5.1–R5.3 *(Track C — blocked: not implemented)*

1. **Services** → create zone `lab.local`, add an A record `r1 → 10.0.0.1`.
2. `dig @<app-ip> r1.lab.local A` → authoritative answer (`aa` flag).
3. `dig @<app-ip> nope.lab.local A` → NXDOMAIN with `aa`.
4. `dig @<app-ip> example.com` → forwarded answer (R5.4).

## AT-09 DHCP — R6.1–R6.5 *(Track C — blocked)*

1. **Services** → define a pool, then a reservation for host-1's MAC.
2. On an Alpine host: `udhcpc -i eth0` → receives the reserved IP.
3. Another host receives the next free address.
4. The lease table shows MAC, IP, hostname, and expiry.
5. Restart the API container → leases still listed (R6.5).

## AT-10 Authentication and roles — R7.1, R7.2 *(Track A — blocked)*

1. Open any URL logged out → redirected to **Login**.
2. Use a wrong password → generic error (does not reveal whether the username exists).
3. Log in as a viewer → Push/Delete controls are disabled; a direct API write returns 403 and is audited.
