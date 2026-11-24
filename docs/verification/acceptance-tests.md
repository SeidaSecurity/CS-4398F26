# Acceptance Test Cases

Derived from the SRS Section 4 stimulus/response sequences. Run them against the live stack
(`scripts\run-lab.ps1` on Windows, or Docker) and the CML lab, never against mock data.
For each step, capture a screenshot of the window, or of the pop-up/dialog if one appears, and save
it in `docs/verification/Acceptance-testSS/` as `AT-xx-step-NN.png` (the Screenshot column gives
the step). Record Actual and Pass/Fail for every step.

**Run log**

| AT | Date | Tester | Build (commit) | Result |
|---|---|---|---|---|
| AT-01 | | | | |
| AT-02 | | | | |
| AT-03 | | | | |
| AT-04 | | | | |
| AT-05 | | | | |
| AT-06 | | | | |
| AT-07 | | | | |
| AT-08 | | | | |
| AT-09 | | | | |
| AT-10 | | | | |

---

## AT-01 Register, edit, and remove a device — R1.1, R1.2, R1.3, R1.4

**Preconditions:** logged in as an administrator; `NETMGR_SECRET_KEY` set in `.env.lab` and the app
restarted; lab router `ios-lab-2` (192.168.198.12) reachable and not yet registered (delete it
first, or use a spare name such as `ios-lab-2b`); `ios-lab-4` (192.168.198.14) powered off.

| # | Action | Expected | Actual | P/F | Screenshot |
|---|---|---|---|---|---|
| 1 | Open **Devices** | Inventory list shown | | | step-01 |
| 2 | Select **Add device** | Add form opens with name, IP, platform, port, SSH username, password, enable secret | | | step-02 |
| 3 | Enter `ios-lab-2`, `192.168.198.12`, `cisco_ios`, 22, the lab username and password; **Test and add** | "Testing connection…", then the device is saved and selected; detail shows **Credentials: Stored (encrypted)**; no password visible anywhere | | | step-03 |
| 4 | Add a second device with the same name (correct details) | Test passes, then error: "A device with that name already exists" | | | step-04 |
| 5 | Edit `ios-lab-2`: change SSH port to 2222, leave the credential fields blank; **Save** | Port updated; still "Stored (encrypted)" (blank keeps the stored credentials) | | | step-05 |
| 6 | Edit again: port back to 22 | Updated value shown | | | step-06 |
| 7 | Delete the device | **Confirmation dialog** appears (SRS 3.1) | | | step-07 |
| 8 | Confirm | Device removed; Audit shows `device.create`, `device.update`, `device.delete` | | | step-08 |

**Alternate A (4.1.4, login refused):** Add `ios-lab-2` with a **wrong password** → red box
"Connection test failed at the **login** stage. The device refused the login…" with **Fix** and
**Save anyway** (screenshot `step-A1`). Press **Fix**, correct the password, **Test and add** →
saved (`step-A2`).

**Alternate B (4.1.4, unreachable):** Add `ios-lab-4`, `192.168.198.14` → within about 3 s, failed at
the **reachability** stage, "Nothing answered on 192.168.198.14:22…" (`step-B1`). Press
**Save anyway** → the device is saved anyway and shows as down after two polls (`step-B2`).

**Alternate C (stored credentials are used):** Push a harmless line (e.g. `banner motd ^AT-01^`)
to the device added in step 3 or A2 → per-device result ✓ succeeded (`step-C1`). This proves the
connector used the stored, encrypted credentials.

## AT-02 Dashboard reflects live state — R2.1, R2.2, R2.3, R2.4, R2.6

**Preconditions:** `MONITORING_ENABLED=true`, `SNMP_COMMUNITY` set, three lab routers registered.

| # | Action | Expected | Actual | P/F | Screenshot |
|---|---|---|---|---|---|
| 1 | Open **Network** (dashboard) | Every device listed with state, last poll time, alerts | | | |
| 2 | Wait one poll interval (default 60 s per R2.1) | Last-poll time advances | | | |
| 3 | Select a device | Detail with CPU, memory, interfaces, throughput graph (CPU and memory from the Cisco MIBs, R2.3) | | | |
| 4 | Change window to 24h / 7d | Graph re-buckets | | | |

## AT-03 Down-device alert — R2.5

**Preconditions:** The lab's "unreachable node" (powered off) is registered.

| # | Action | Expected | Actual | P/F | Screenshot |
|---|---|---|---|---|---|
| 1 | Wait one poll | Device still **up**, failures = 1 | | | |
| 2 | Wait a second poll | Device **down**, alert raised, sorted to top and visually distinct | | | |
| 3 | Power the node on; wait one poll | Device **up**, alert resolved | | | |

**Alternate (CPU threshold, R2.5):** set `CPU_ALERT_PERCENT=1` in `.env.lab` and restart (idle IOSv
reports about 1% or 0%; if CPU stays 0, generate load with `ping 192.168.198.1 repeat 100000 size
1500` on the router). Expected: an alert "ios-lab-N CPU at X% (alert threshold 1%)" appears. Set
the variable back to 90 and restart; after the next poll the CPU alert is resolved. While a CPU
alert is open, stopping that node still raises its separate down alert (checkpoint F).

## AT-04 Push configuration to several devices with one failure — R3.1, R3.2, R3.5, R3.7

**Preconditions:** `ios-lab-1` and `ios-lab-2` reachable; `ios-lab-4` registered but powered off.

| # | Action | Expected | Actual | P/F | Screenshot |
|---|---|---|---|---|---|
| 1 | Open **Push** | Editor, device selector, templates | | | |
| 2 | Choose template; fill variables | Rendered preview shown | | | |
| 3 | Leave a variable empty | Error "Missing template values: …" | | | |
| 4 | Select all three devices; click **Push** | **Confirmation dialog** lists the targets and the rendered config (4.3.4 step 3) | | | |
| 5 | Confirm | Per-device summary: lab-1 ✓, lab-2 ✓, lab-4 ✗ unreachable; lab-1/2 still complete | | | |
| 6 | Open **History** for lab-1 | New `pre_push` and `post_push` versions with operator and time | | | |

## AT-05 Compare and roll back versions — R3.3, R3.4, R3.6

| # | Action | Expected | Actual | P/F | Screenshot |
|---|---|---|---|---|---|
| 1 | **History** → choose two versions | Side-by-side diff, +/− counts (computed by the server, `GET …/config/diff`) | | | |
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

## AT-08 DNS — R5.1, R5.2, R5.3, NFR-3

**Preconditions:** logged in as admin; `DNS_ENABLED=true` in `.env.lab` and the app restarted;
no other program on port 53. Run the commands in a PowerShell window on the lab PC.

| # | Action | Expected | Actual | P/F | Screenshot |
|---|---|---|---|---|---|
| 1 | Open **Services** | DNS zones table (empty or existing zones) and help text in the side panel | | | step-01 |
| 2 | **Add zone** `lab.local` (default TTL 3600) | Zone listed with 0 records; inline help visible under each field | | | step-02 |
| 3 | Select `lab.local`; **Add record** `r1`, type A, `192.168.198.11` | Record listed as `r1.lab.local`, TTL "default (3600 s)" | | | step-03 |
| 4 | Add record `r1`, type CNAME, `r2.lab.local` | Error: a CNAME cannot share a name with other records (RFC 1034) | | | step-04 |
| 5 | Add zone `198.168.192.in-addr.arpa`; add record `11`, PTR, `r1.lab.local` | Reverse zone and PTR listed | | | step-05 |
| 6 | `Resolve-DnsName r1.lab.local -Server 127.0.0.1 -DnsOnly` | Answer `192.168.198.11` | | | step-06 |
| 7 | `Resolve-DnsName 192.168.198.11 -Server 127.0.0.1 -DnsOnly` | Answer `r1.lab.local` (PTR) | | | step-07 |
| 8 | `Resolve-DnsName no-such-host.lab.local -Server 127.0.0.1 -DnsOnly` | Error: DNS name does not exist (NXDOMAIN) | | | step-08 |
| 9 | `.venv\Scripts\python scripts\dns_probe.py r1.lab.local --repeat 5` | `"rcode": "NOERROR", "aa": true`, median < 50 ms (NFR-3) | | | step-09 |
| 10 | Select record `r1` (A) → **Delete** | **Confirmation dialog** naming `r1.lab.local` | | | step-10-dialog |
| 11 | Confirm, then repeat step 6 | Record gone; step 6 now returns NXDOMAIN, no restart needed | | | step-11 |
| 12 | Log in as a **viewer** and open Services | Zones and records visible; no Add/Delete/Save controls | | | step-12 |

**Alternate:** set `DNS_PORT` to a port another program holds and restart. Expected: the API
window logs "DNS could not listen…", the app (syslog, polling, UI) keeps working, and
`check-lab.ps1` shows the DNS rows failing with the "Is port … free?" hint.

**Out of scope here (Desirable, later):** forwarding names outside local zones (R5.4); for now
`example.com` returns REFUSED.

## AT-09 DHCP — R6.1–R6.5

**Preconditions:** logged in as admin. Steps 1–4 need only the app. Steps 5–7 need a DHCP client
on an isolated lab segment (the VMnet2 host-only network, with VMware's own DHCP off) and
`DHCP_ENABLED=true`, `DHCP_SERVER_IP=192.168.50.1`; they are deferred with NFR-2 if that segment
isn't ready.

| # | Action | Expected | Actual | P/F | Screenshot |
|---|---|---|---|---|---|
| 1 | **Services** → **DHCP** tab | Pools table, help text, note that DHCP starts after a restart once a pool exists | | | step-01 |
| 2 | **Add pool** `lab-50`: 192.168.50.100–192.168.50.150, mask 255.255.255.0, gateway/DNS 192.168.50.1, lease 3600 | Pool listed | | | step-02 |
| 3 | Add a pool overlapping the first | Error "Subnet … overlaps pool 'lab-50' … Pools must not overlap." (409) | | | step-03 |
| 4 | Select `lab-50` → **Add reservation** for a client's MAC → 192.168.50.120 | Reservation listed | | | step-04 |
| 5 | On the reserved client: `udhcpc -i eth0` (Alpine) or `ip dhcp` / renew | Receives 192.168.50.120 | | | step-05 |
| 6 | A second client requests an address | Receives 192.168.50.100 (the lowest free address) | | | step-06 |
| 7 | Leases table; then restart the app and reopen | MAC, IP, hostname, state, expiry shown; still listed after the restart (R6.5) | | | step-07 |
| 8 | **Delete pool** | **Confirmation dialog** stating how many active leases and reservations will be dropped | | | step-08 |

## AT-10 Authentication and roles — R7.1, R7.2, R7.4

| # | Action | Expected | Actual | P/F | Screenshot |
|---|---|---|---|---|---|
| 1 | Open the app logged out | **Login** screen | | | step-01 |
| 2 | Log in with a wrong password | Generic error that doesn't reveal whether the username exists | | | step-02 |
| 3 | Log in as admin → **Accounts** → create viewer `vic` | Account listed with role viewer | | | step-03 |
| 4 | Log out; log in as `vic` | Push and Accounts missing from the menu; no Add/Delete/Restore controls on Devices, History, Services | | | step-04 |
| 5 | As `vic`, call a write directly, e.g. `Invoke-WebRequest -Method Delete http://127.0.0.1:8000/api/v1/devices/1` with the viewer's session cookie | 403 "Your account is read-only (viewer), so this change was not made…"; Audit (as admin) shows `access.denied` | | | step-05 |
| 6 | As admin, disable `vic` | `vic`'s session stops working on the next request | | | step-06 |
