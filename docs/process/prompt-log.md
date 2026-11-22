# Prompt Log (Deliverable 1)

One entry per meaningful agent session. Keep the actual prompt text; summarize the response.
Earlier work (before 2026-11-17) was not logged consistently. Reconstruct what you can from
commit history and chat exports, and mark those entries "reconstructed".

| # | Date | Author | Agent / model | Requirement(s) | Commit / PR |
|---|---|---|---|---|---|
| P-001 | 2026-11-17 | Justin | Claude Code (Opus 5.5) | process, all | (uncommitted) |
| P-002 | 2026-11-17 | Justin | Claude Code (Opus 5.5) | R2.1, R4.3, R4.4, R3.2, R3.5, R1.2, 5.3.3, 10.4 | (uncommitted) |
| P-003 | 2026-11-18 | Justin | Claude Code (Opus 5.5) | SRS 8.3–8.4 (lab), 5.3.4, ADR-0003 | (uncommitted) |
| P-004 | 2026-11-19 | Justin | Claude Code (Opus 5.5) | R7.1–R7.4, R3.3, R4.4, NFR-5; SRS 3.1.1 | branch `track-a/7-auth-roles` |
| P-005 | 2026-11-19 | Justin | Claude Code (Opus 5.5) | R5.1–R5.3, NFR-3, SRS 5.3.1, 5.3.5 | branch `track-c/8-dns-authoritative` |
| P-006 | 2026-11-20 | Justin | Claude Code (Opus 5.5) | R6.1–R6.3, R6.5–R6.7; SRS 5.3.1 | branch `track-c/9-dhcp` |

---

## P-001 — Documentation and V&V audit

**Context given:** SRS PDF, the instructor's deliverables announcement, the repository at `632ae38`.

**Prompt:**
> I need to set up this extra documentation and get suggestions on how to improve the code to
> adhere with the SRS requirements and the development processes such as MoT.

**What the agent did:** Ran the tests (23 pass, 80% coverage), `ruff` (clean), and `mypy`
(11 errors). Audited every R-ID against the code. Created `CLAUDE.md`, the RTM, the V&V plan,
acceptance tests, the class diagram, statecharts, the architecture description, ADRs, the
improvement plan, and the CI workflow.

**Human verification:** _(fill in: what you checked, what you changed)_

---

## P-002 — MoT session: SRS conformance fixes from the improvement plan

**Context given (Prompt 0):** `CLAUDE.md`, the SRS PDF, `docs/improvement-plan.md`, a description
of MoT (Module of Thought).

**Prompt:**
> MoT stands for Module of Thought, let me know which file to put human verification in and
> implement those fixes mentioned

**Plan (checkpoints labeled before execution):**

| Inc | Capability | Requirement | Checkpoint (risk → isolation test) |
|---|---|---|---|
| 0 | Load context, measure baseline | — | — |
| 1 | Default poll interval 60 s | R2.1 | — |
| 2 | Audit template create/update/delete | R4.4 | — |
| 3 | Literal `%`/`_` in log search | R4.3 | — |
| 4 | Extract `ConfigurationService` (no behavior change) | design (SRP/DRY) | ⚠ Transaction order: the pre-change snapshot must commit before the device is touched → existing push/restore tests must pass **unchanged** |
| 5 | Classify outcomes: rejected / unreachable / unverified / not_found | R3.5, SRS 4.3.4 5b/5c | ⚠ API contract change → back-end tests, then `tsc` on `web/`, then update `contracts.md` |
| 6 | Operator-facing error messages; technical detail only in the audit log | SRS 5.3.3 | — |
| 7 | Fix mypy errors without loosening PATCH validation | SRS 10.4 | ⚠ `str \| None` would let explicit nulls reach NOT NULL columns → regression test for 422 |

**Performance tracking matrix** (🟢 all pass, coverage ≥ baseline · 🟡 pass but degraded · 🔴 fail)

| Inc | Tests passed / total | Coverage | ruff | mypy | tsc | Zone | Notes |
|---|---|---|---|---|---|---|---|
| 0 | 23 / 23 | 80% | 0 | 11 | — | baseline | |
| 1–3 | 30 / 30 | — | 0 | 11 | — | 🟢 | New tests: 5 of 7 fail on the old code (fail-before check); the 2 that pass are the ordinary-input controls |
| 4 | 30 / 30 | — | 1 (E501) → 0 | 11 | — | 🟢 | Oracle passed: push/restore tests unchanged and green; `main.py` 464 → 385 lines |
| 5–6 | 32 / 34 → 34 / 34 | — | 0 | — | — | 🔴 → 🟢 | Degradation analysis: both failures were *intended* contract changes (`failed` → `rejected`/`not_found`; raw `RuntimeError` text now hidden). The fake connector now raises `DeviceRejectedError`, and the expectations and `contracts.md` were updated |
| 5b | 53 / 53 | — | 0 | — | 0 errors | 🟢 | Added `tests/test_configuration.py` (Netmiko classification, credentials). Front-end `ChangeStatus` type, mock, and Push labels updated |
| 7 | 55 / 55 | **86%** | 0 | **0** | 0 errors | 🟢 | `PartialUpdate` rejects explicit nulls; CI mypy step made blocking |

**Not verified in this session:** `vite build` could not run locally, because Node 22.5.1 is older
than the project's required ≥ 22.12, so a native binding is missing. CI uses a current Node 22.
No lab (GNS3) test was run. The rejection regex matches the standard IOS `% Invalid input`,
`% Incomplete command`, and `% Ambiguous command` messages, but confirm it against the real lab image.

**Human verification:** _(fill in: re-run `pytest`, read `app/config_service.py` and
`tests/test_api.py::test_r3_5_*`, and be ready to explain why read-back failure is "unverified")_

---

## P-003 — MoT session: run the app natively on Windows for CML lab sessions

**Context given (Prompt 0):** `CLAUDE.md`, `lab/README.md`, `.env.lab` (git-ignored; never read
by the agent), `.env.example`, `app/main.py`, `docs/decisions/0003-pin-paramiko-for-iosv.md`.
Earlier in the session, lab bring-up had found that IOSv offers only SHA-1 SSH key exchange, so
paramiko was pinned below 5 (ADR-0003).

**Prompt** (drafted with the agent's help after several clarifying questions; sent verbatim):
> Context: CLAUDE.md, lab/README.md, .env.lab (exists, git-ignored, filled in), .env.example,
> app/main.py (lifespan starts syslog + poller), docs/decisions/0003-pin-paramiko-for-iosv.md.
> Goal: run the full app natively on Windows for CML lab sessions, without Docker
> (WSL/Hyper-V must stay off while CML runs).
>
> My environment: Windows 11, PowerShell, Python 3.14 (project needs >= 3.11), Node 22.12+.
> No project venv yet. CML lab on VMware NAT (VMnet8) 192.168.198.0/24: my PC is
> 192.168.198.1, routers ios-lab-1..3 at .11-.13 are booted, ios-lab-4 (.14) is
> intentionally stopped. Verified: ping and SSH to .11 work (IOSv needs SHA-1 KEX; paramiko
> is pinned <5 for that). Database: SQLite for lab sessions.
>
> Increments, one capability each:
> 1. A committed .env.lab.example with placeholders only (mirror the keys in my .env.lab, no
>    secrets) so teammates can recreate it.
> 2. scripts/run-lab.ps1: creates or uses .venv, checks the Python and Node versions, that
>    .env.lab exists, and that the installed paramiko is < 5; then starts uvicorn with
>    --env-file .env.lab and, in a second window, the web UI in live mode. Clear error
>    messages if a check fails.
> 3. scripts/check-lab.ps1: smoke test. GET /health, send one test syslog message to UDP 514
>    and confirm it appears in GET /api/v1/logs, ping .11-.14, test TCP 22 on each. Print a
>    pass/fail table (.14 is expected to fail).
> 4. A "Run natively on Windows" section in lab/README.md, including the firewall rule for
>    UDP/TCP 514 on the Public profile.
>
> Before coding: show the plan with critical checkpoints (Windows-specific risks: port 514
> binding, ICMP on Windows, SQLite path, env loading). Wait for my OK.
> Constraints: no app code changes unless a Windows bug is found (explain it first);
> never print or copy values from .env.lab; don't commit; don't edit the prompt log.
> Done when: ruff/mypy/pytest still pass, and check-lab.ps1 run against my lab prints a
> pass/fail table.

Follow-up after the plan: "go ahead with increments 1-4 and update the prompt log with the previous prompt."

**Pre-flight checks found two mismatches with the prompt's assumptions:** Node was still
v22.5.1 (not ≥ 22.12), and `.env.lab` still had 5 `REPLACE_WITH_*` placeholders. The agent
counted the placeholders without reading any values.

**Plan (checkpoints labeled before execution):**

| Inc | Deliverable | Checkpoint (risk → isolation test) |
|---|---|---|
| 0 | Baseline | — |
| 1 | `.env.lab.example` | — |
| 2 | `scripts/run-lab.ps1` (+ `-CheckOnly`, `-NoWeb`, `-Reinstall`) | ⚠ A: env loading order / shell variables taking priority → confirmed uvicorn loads `--env-file` before importing the app; warn on shadowed keys. ⚠ B: SQLite path relative to the working directory → always switch to the repo root; no `--reload`. ⚠ C: Windows script-execution policy → documented `-ExecutionPolicy Bypass` |
| 3 | `scripts/check-lab.ps1` | ⚠ D: a local syslog test passes even if the firewall blocks the routers (false confidence) → separate firewall-rule check. ⚠ E: Windows ping working doesn't prove the *app's* ping works → report the app's own monitoring state |
| 4 | README section | — |

**Performance tracking matrix** (🟢 all pass, no regression · 🟡 degraded · 🔴 fail)

| Inc | Tests | Coverage | ruff | mypy | Script result | Zone | Notes |
|---|---|---|---|---|---|---|---|
| 0 | 55 / 55 | 86% | 0 | 0 | — | baseline | |
| 1 | 55 / 55 | 86% | 0 | 0 | — | 🟢 | `.gitignore` rule `.env.*` would have hidden the example too → added a `!.env.lab.example` exception. Key parity checked by comparing key names only |
| 2 | 55 / 55 | 86% | 0 | 0 | `-CheckOnly`: created `.venv`, installed paramiko 4.0.0 (pin works), stopped correctly at the 5 placeholders | 🟢 | Agent self-review fixed two Windows PowerShell 5.1 issues before running: redirected native stderr becomes a terminating error; importing `app.main` created the SQLite file. Node version check boundary-tested (22.5.1 ✗, 22.11 ✗, 22.12 ✓, 20.18 ✗, 20.19 ✓, 21.7 ✗, 24.1 ✓) |
| 3 | 55 / 55 | 86% | 0 | 0 | Ran against a throwaway API (scratch SQLite, 10 s polls) and the real lab: 5 PASS, 11 FAIL | 🔴 → 🟢 (script) | See degradation analysis below |
| 4 | 55 / 55 | 86% | 0 | 0 | — | 🟢 | README: setup, firewall (Admin, Public profile), execution policy, Docker as the alternative |

**Degradation analysis (Inc 3):**
1. *All routers "down" in the app, while the user had pinged .11 earlier.* The first hypothesis
   was that Windows Firewall drops ICMP replies to icmplib's raw socket. A second test, using the
   Windows ICMP API (`IcmpSendEcho`), also failed, which undercut that hypothesis. A third check
   found plain `ping.exe` and TCP 22 failing too: **the lab was unreachable at that moment** (a
   `vEthernet (WSL ...)` adapter was present). Conclusion: no app bug. The hypothesis was
   withdrawn, and no app code was changed.
2. *Real script bug:* Windows PowerShell 5.1 returns a JSON array from `Invoke-RestMethod` as a
   single object, so `@(...)` counted 4 devices as 1. Fixed with a `Get-ApiList` helper that enumerates.
3. *Misleading hint:* "App ICMP disagrees with Windows ping" was shown even though Windows ping
   had failed too. The hint now depends on the Windows ping result ("fix the lab first").


**Human verification:** Node version upgrade successful and lab test cases pass.

---

## P-004 — MoT session: authentication, roles, and accounts (Track A, taken over by Justin)

**Context given (Prompt 0):** `CLAUDE.md`, SRS §4.7, §3.1.1, §5.2, R3.3/R4.4, `docs/contracts.md`,
`app/main.py`, `app/monitoring.py`, `app/models.py`, `web/src/`, `scripts/check-lab.ps1`.
Four design decisions were made *before* the prompt, in conversation: cookie sessions,
argon2, the first admin from env, and `require_admin` on writes.

**Prompt** (drafted with the agent, sent verbatim). The user added "remember to update prompt
log", which overrode the prompt's own "don't edit the prompt log" line:
> Context: CLAUDE.md, SRS §4.7 (R7.1-R7.5), §3.1.1 (login screen), §5.2 (NFR-5), R3.3 and R4.4,
> docs/contracts.md, app/main.py, app/monitoring.py, app/models.py, web/src/,
> scripts/check-lab.ps1. This changes the frozen REST auth contract (SRS 9.4), so record it
> in docs/decisions/.
>
> Decisions already made (do not re-decide):
> - Sessions: HTTP-only, SameSite=Lax cookie holding a random token; server-side sessions
>   table stores only the token's hash and an expiry, so disabling a user revokes access at once.
> - Passwords: argon2 via argon2-cffi. NIST 800-63B rule: 8-64 characters, rejected if on a
>   bundled list of common passwords. Never log or return a password or hash.
> - First admin: created at startup from ADMIN_USERNAME / ADMIN_PASSWORD only when no users
>   exist. Add both keys (placeholders only) to .env.lab.example.
> - Roles: admin and viewer. A require_admin dependency on every state-changing route returns
>   403 and writes an audit record of the refusal (R7.2). /health stays public.
>
> Increments, one capability each:
> 1. User model, password hashing and policy (R7.3, NFR-5).
> 2. Admin bootstrap from env.
> 3. POST /auth/login, POST /auth/logout, GET /auth/me. Failed logins get one generic message
>    that doesn't reveal whether the username exists (3.1.1); audit success and failure (R4.4).
> 4. Require a logged-in user on every /api/v1 route (R7.1) and admin on every write (R7.2).
> 5. Replace the caller-supplied `operator` (query param and push body) with the logged-in
>    username (R3.3, R4.4).
> 6. Admin-only account management: create, change role, disable (R7.4); audited; a disabled
>    user can't log in; the last active admin can't be disabled or demoted.
> 7. Web: Login screen, redirect to login on 401, write controls hidden for viewers, a minimal
>    Accounts screen. Keep mock mode working.
> 8. scripts/check-lab.ps1 logs in (reading ADMIN_* from .env.lab, never printing them), and
>    lab/README.md documents it.
>
> Critical checkpoints to address in the plan:
> A. ~75 existing tests call an open API: a test fixture logs in as admin; no other assertions
>    may change.
> B. A test that enumerates app.routes and proves every write route rejects a viewer (403) and
>    every /api/v1 route rejects an anonymous caller (401), so a future route can't slip
>    through.
> C. The `operator` removal is an API contract change: update contracts.md and the front-end
>    types; tsc must pass.
> D. run-lab.ps1 and check-lab.ps1 must still work against my lab.
>
> Before coding: show the baseline and the plan, with how each checkpoint is tested. Wait for my OK.
> Constraints: tests named test_r7_N_...; tests fail before and pass after; thin routes (auth
> logic in its own module); update the RTM each increment; don't commit; don't edit the
> prompt log.
> Done when: ruff, mypy, pytest (coverage ≥ 70%) and tsc pass; I can log in as admin and as
> viewer on the lab and see the viewer blocked from a push; report one tracking-matrix row
> per increment.

**Plan review.** The agent proposed four design points; the user approved all four ("design
points 1-4 are good, Ok to proceed"):
1. One **central access policy** (an app-wide dependency) instead of a check on each route.
2. Auth endpoints under `/api/v1/auth/…`.
3. Sessions last 8 hours from login; idle timeout (R7.5) deferred.
4. The template-render POST counts as a write.

Two **new checkpoints were found during planning**, from reading the code:
- **E, the `app.routes` trap:** in FastAPI 0.165, routes added with `include_router` (all six
  monitoring routes) don't appear in `app.routes`. Checkpoint B as written would have
  silently skipped them. The route walk uses the OpenAPI schema instead, and asserts a minimum
  operation count so a partial walk fails.
- **F, no migrations:** add only new tables, so the user's lab database keeps its devices.

**Performance tracking matrix** (🟢 all pass, no regression · 🔴 fail → analysed)

| Inc | Tests | Cov | ruff | mypy | tsc | Zone | Notes |
|---|---|---|---|---|---|---|---|
| 0 | 75 / 75 | 87% | 0 | 0 | ✅ | baseline | 23 routes (from OpenAPI) |
| 1 | 99 / 99 | 87% | 0 | 0 | — | 🟢 | Users, argon2id, NIST policy, sessions stored as hashes. 24 new tests failed first |
| 2 | 104 / 104 | 87% | 0 | 0 | — | 🟢 | Admin from env; startup never touches the DB when it's unset |
| 3 | 111 / 111 | 89% | 0 | 0 | — | 🟢 | Login, logout, me: byte-identical failure bodies, HTTP-only Lax cookie. First fail-before was a test-import mistake, fixed before counting |
| 4 | 117 / 117 | 89% | 1 → 0 | 0 | — | 🔴 → 🟢 | The policy turned 24 existing tests into 401s, as predicted. Fixed with 2 fixture lines per file and **0 assertion changes**. The route walk covers all 26 operations |
| 5 | 118 / 118 | 89% | 1 → 0 | 0 | ✅ + build | 🔴 → 🟢 | Exactly 2 tests failed: the intended contract change (actor = logged-in user). The Push screen's free-text "Operator" box was found and removed |
| 6 | 128 / 128 | 90% | 0 | 0 | — | 🟢 | Accounts API with last-admin protection. The 3 new routes were **automatically** covered by the route walk |
| 7 | 128 / 128 | 90% | 0 | 0 | ✅ + build | 🟢 | Login screen, role-aware navigation, Accounts screen, write controls hidden for viewers. Verified manually on the lab |
| 8 | 128 / 128 | 90% | 0 | 0 | ✅ | 🟢 | `check-lab.ps1` logs in: **17/17 PASS against the real lab**. `run-lab.ps1` checks the admin password against the app's own policy |

**Lab findings (validation catching what unit tests can't):**
1. *Login didn't work after the first restart.* The agent diagnosed it without reading secret
   values: `ADMIN_PASSWORD` was 6 characters, so the policy rejected it at startup and created
   no admin. The only signal was a log line in the API window. Fixed by the user, and the gap was
   closed in increment 8: `run-lab.ps1` now refuses to start with a password the policy would
   reject (the check calls `app.auth.validate_password`, so there is one source of truth).
2. *Windows PowerShell 5.1:* `$PSScriptRoot` is empty inside `param()` defaults, so `check-lab.ps1`
   failed on first run. The default is now resolved after the parameter block.

**Not verified in this session:** automated UI tests (none exist yet, so increment 7 is covered by
`tsc` plus manual lab checks); idle-session expiry (R7.5, deferred); HTTPS (NFR-7).

**Human verification:** admin account login and viewer only account creation successful. Refusal of options based on role verified.

---

## P-005 — MoT session: authoritative DNS service (Track C, taken over by Justin)

**Context given (Prompt 0):** `CLAUDE.md`, SRS §4.5, §3.1.6, §5.1 (NFR-3), §5.3.1, §5.3.5, §6.1,
`docs/contracts.md`, `app/main.py`, `app/auth.py`, `docs/verification/acceptance-tests.md`.
Track C was reassigned because its original owner had delivered nothing. DNS went first because it
is smaller, easy to demonstrate, and DHCP's lease registration (R5.6) depends on it.

**Prompt** (drafted with the agent, sent verbatim):
> Context: CLAUDE.md, SRS §4.5 (R5.1-R5.6), §3.1.6 (Services screen), §5.1 (NFR-3), §5.3.1
> (robustness), §5.3.5 (in-program help), §6.1 (RFC 1035), docs/contracts.md, app/main.py
> (lifespan), app/auth.py (central access policy), docs/verification/acceptance-tests.md (AT-08).
> Goal: an authoritative DNS server for operator-defined zones (Track C, now built by me).
>
> Decisions already made (do not re-decide):
> - Library: dnslib (add to pyproject). UDP and TCP on DNS_HOST/DNS_PORT (default 0.0.0.0:53),
>   started from the app lifespan only when DNS_ENABLED=true; a bind failure is logged and the
>   rest of the app keeps running (SRS 5.3.1).
> - Code lives in its own package app/dns/ (resolver.py, server.py, routes.py) as a separate
>   subsystem (SRS 5.3.2); tables stay in app/models.py. New tables only (no migrations).
> - Record types: A, AAAA, CNAME, PTR (R5.1). Zones include reverse zones (in-addr.arpa) for PTR.
> - Names are case-insensitive. A CNAME cannot share a name with any other record (RFC 1034).
> - Names outside every local zone get REFUSED for now; forwarding and caching (R5.4/R5.5) and
>   DHCP registration (R5.6) are Desirable and come later.
> - Zone and record changes are admin-only (the central policy handles that) and audited.
>
> Increments, one capability each:
> 1. Zone and record tables plus validation: zone names, values per type (IPv4 for A, IPv6 for
>    AAAA, hostname for CNAME/PTR), TTL bounds, CNAME exclusivity (R5.2).
> 2. A pure resolver (no sockets): authoritative answers with the AA flag (R5.1), CNAME
>    followed inside the zone, NXDOMAIN with the zone's SOA in the authority section (R5.3),
>    NOERROR/no-data when the name exists but not that type, REFUSED outside local zones.
> 3. UDP+TCP server lifecycle in the app lifespan; integration test with a real query on an
>    ephemeral port (like the syslog receiver test).
> 4. REST API for zones and records (CRUD), audited (R4.4), operator-facing errors (SRS 5.3.3).
> 5. Services screen, DNS part (SRS 3.1.6): zones list, records table, add/edit/delete with
>    confirmation for deletes, inline help describing each field's format (SRS 5.3.5).
> 6. Lab: DNS keys in .env.lab.example; check-lab.ps1 resolves a test record via
>    Resolve-DnsName and reports the response time against NFR-3 (< 50 ms); lab/README and
>    AT-08 updated to match.
>
> Critical checkpoints to address in the plan:
> A. RFC 1035 correctness: tests build real query packets with dnslib and check the reply's
>    flags (AA, rcode), answer and authority sections, not just Python return values.
> B. Port 53 on my Windows machine may be taken by another service: make the port
>    configurable, make check-lab report a clear failure, and document how to find the
>    process using it.
> C. The access-policy route test must automatically cover the new DNS routes; update its
>    minimum operation count.
> D. Server threads must stop cleanly on shutdown, and a DNS failure must not stop syslog or the
>    poller.
>
> Before coding: show the baseline and the plan, with how each checkpoint is tested. Wait for my OK.
> Constraints: tests named test_r5_N_...; tests fail before and pass after; thin routes; update
> the RTM and contracts.md each increment; add a decision record for the DNS design; don't
> commit; flag good commit points; add prompt-log entry P-005 for this prompt when finished.
> Done when: ruff, mypy, pytest (coverage ≥ 70%) and npm run build pass, and on the lab
> `Resolve-DnsName r1.lab.local -Server 127.0.0.1` returns an authoritative answer, a missing
> name returns NXDOMAIN, and a PTR lookup works.

**Plan review.** The agent proposed four design points; the user approved them as written:
1. Read zones from the database on every query (no cache to keep in sync; measure NFR-3).
2. Answer SOA queries at the apex; the SOA is generated from the zone, with negative TTL 300 s.
3. TTL range 30–604800 s; the most specific matching zone wins.
4. CNAMEs are followed only inside local zones, at most 8 hops.

**Finding during planning:** the syslog listener crashed the whole app when port 514 was taken,
which already broke SRS 5.3.1. The user approved fixing it in the same work. Also checkpoint E:
naming the package `app/dns` is safe (it's namespaced under `app`).

**Performance tracking matrix** (🟢 all pass, no regression · 🔴 fail → analysed)

| Inc | Tests | Cov | ruff | mypy | tsc | Zone | Notes |
|---|---|---|---|---|---|---|---|
| 0 | 128 / 128 | 90% | 0 | 0 | ✅ | baseline | Port 53 free; 29 routes |
| 1 | 164 / 164 | 90% | 0 | 0 | — | 🟢 | Zone/record rules: label 63/64, name 253/254, TTL 29/30/604800/604801, CNAME exclusivity both ways, no CNAME at the apex. 36 new tests failed first |
| 2 | 183 / 183 | 90% | 3 → 0 | 0 | — | 🟢 | Pure resolver. **Every test round-trips a real DNS packet through wire format** and checks AA, rcode, answer and authority sections. Includes a CNAME loop (→ SERVFAIL) and empty non-terminals (RFC 8020). 19 new tests failed first |
| 3 | 191 / 191 | 91% | 0 | 0 | — | 🟢 | Real UDP and TCP queries; clean stop releases both ports (dnslib's `stop()` alone doesn't). **Syslog fix proven fail-before:** the old code crashed startup with `WinError 10048` |
| 4 | 200 / 200 | 92% | 7 → 0 | 0 | — | 🟢 | 8 REST operations, audited, 422/409/404. The route walk covered them automatically (minimum 29 → 37). An end-to-end test goes from API create to resolver answer |
| 5 | 200 / 200 | 92% | 0 | 0 | ✅ + build | 🟢 | Services screen with inline help for every field (SRS 5.3.5) and delete confirmations. The first attempt to apply the API changes failed on shell quoting and changed nothing; this was verified before redoing it |
| 6 | 203 / 203 | 92% | 4 → 0 | 0 | ✅ | 🟢 | `scripts/dns_probe.py`, written *before* its 3 tests (no fail-before for this tooling, noted honestly). `check-lab.ps1` has 4 DNS rows: **21/21 PASS** against a throwaway DNS server on port 5353, median **1.25 ms** (NFR-3). The failure path shows the "is DNS enabled / is the port free" hint |

**Not verified in this session:** DNS on the real lab with your own `.env.lab` (it needs
`DNS_ENABLED=true` and the records created on the Services screen), so the NFR-3 figure on the
lab's SQLite file is still to be measured. No automated UI tests.

**Human verification:** _(fill in: the AT-08 run on the lab, i.e. the three Resolve-DnsName
results, dns_probe showing AA and the median ms, the delete confirmation, and the viewer
read-only view; be ready to explain NXDOMAIN vs NOERROR/no-data and why the tests round-trip
through wire format)_

---

## P-006 — MoT session: DHCP core (pools, codec, allocator, UDP server), increments 1–4

**Context given (Prompt 0):** `CLAUDE.md`, SRS §4.6, §3.1.6, §5.1 (NFR-2), §5.3.1, §5.3.5,
§6.1, §6.2, statechart §7, ADR-0006 (structure to mirror), `app/dns/` (pattern), `app/main.py`.
The session was deliberately split: increments 1–4 (logic, provable without the lab) now; API,
screen and lab in a follow-up prompt.

**Prompt** (drafted with the agent, sent verbatim):
> Context: CLAUDE.md, SRS §4.6 (R6.1-R6.7), §3.1.6 (Services screen), §5.1 (NFR-2), §5.3.1,
> §5.3.5, §6.1 (RFC 2131), §6.2 (raw-socket spike / fallback), docs/design/statecharts.md §7
> (DHCP lease), docs/decisions/0006-authoritative-dns-design.md (follow the same structure),
> app/dns/ (pattern to mirror), app/main.py (lifespan).
> Goal: a DHCP server that issues and tracks leases from operator-defined pools (Track C).
>
> Decisions already made (do not re-decide):
> - Own package app/dhcp/ (rules, packet codec, allocator, server, routes); tables in
>   app/models.py, new tables only.
> - No raw sockets and no scapy: a standard UDP socket on port 67 with SO_BROADCAST, replies
>   broadcast to 255.255.255.255:68 (RFC 2131 §4.1 allows this). The packet codec is our own
>   (struct-based), covering the BOOTP header and the options we use: 1, 3, 6, 12, 15, 50, 51,
>   53, 54, 55, 61, 255.
> - Safety: DHCP only starts when DHCP_ENABLED=true AND DHCP_SERVER_IP is set to an address on
>   the bound interface that lies inside a configured pool's subnet; otherwise it logs why and
>   stays off. It must never answer on networks it has no pool for.
> - Allocation order (R6.1/R6.3): the MAC's reservation, then the MAC's existing lease, then the
>   lowest free address in the pool. Offers are held briefly; exhaustion sends no offer and
>   writes a log record (R6.7) into the existing syslog store.
> - Leases persist in the database (R6.5); expired or released leases free their address (R6.6).
> - Pool, reservation and lease changes are admin-only (central policy) and audited.
>
> Increments, one capability each:
> 1. Pool, reservation and lease tables plus validation: subnet CIDR, range inside the subnet
>    (not the network or broadcast address), gateway in the subnet, DNS server list, domain,
>    lease-time bounds, normalized MACs, reservation inside its pool's subnet, no overlapping
>    pools (R6.2, R6.3).
> 2. Packet codec: parse and build DHCP messages; reject truncated packets, a missing magic
>    cookie, and malformed options.
> 3. Pure allocator implementing statechart §7: DISCOVER→OFFER, REQUEST→ACK or NAK
>    (selecting, renewing, wrong server), RELEASE, expiry sweep, exhaustion (R6.1, R6.6, R6.7).
> 4. UDP server lifecycle in the app lifespan with the safety check above, bind-failure
>    robustness like DNS, and an integration test of a full DORA exchange over localhost UDP.
> 5. REST API: pools and reservations CRUD, active leases list, audited (R6.2-R6.4).
> 6. Services screen DHCP section: pools, reservations, active leases (MAC, IP, hostname,
>    expiry) with inline help for every field (completes SRS 5.3.5).
> 7. Lab: an isolated CML segment without VMware DHCP, .env.lab.example keys, check-lab rows, a
>    load script for NFR-2 (20 concurrent clients, DISCOVER answered in < 500 ms), lab/README
>    and AT-09 updated.
>
> Critical checkpoints to address in the plan:
> A. RFC 2131 wire correctness: tests work on bytes (header fields, flags, magic cookie,
>    option encoding), round-tripped through the codec, not just Python objects.
> B. Rogue-DHCP safety: a test proves the server refuses to start without a matching pool and
>    interface, and never replies for an unknown subnet.
> C. Address uniqueness: two clients can never hold the same address, even when requests
>    arrive concurrently (database constraint plus an allocator test).
> D. Persistence: leases survive an app restart (R6.5), proven by a test.
> E. Windows feasibility: receiving broadcasts and sending broadcast replies on Windows is
>    unproven. Time-box a lab spike to 1 hour inside increment 7; if it fails, document the
>    fallback (run the stack in an Ubuntu VM on the same segment, SRS 6.2) in an ADR.
> F. The access-policy route walk covers the new routes; update its minimum operation count.
>
> Before coding: show the baseline and the plan, with how each checkpoint is tested. Wait for my OK.
> Do increments 1-4 in this session; 5-7 come in a follow-up prompt.
> Constraints: tests named test_r6_N_...; tests fail before and pass after; thin routes; update
> the RTM and contracts.md each increment; add ADR-0007 for the DHCP design; don't commit;
> flag good commit points; add prompt-log entry P-006 for this prompt when finished.
> Done when (this session): ruff, mypy and pytest (coverage ≥ 70%) pass, and the localhost
> DORA integration test passes over real UDP sockets.

**Planning findings (from read-only checks on the dev PC):**
- **Checkpoint G, a multi-homed host:** the PC has 5 adapters, including a **real network**
  (`192.168.1.49`). Binding `0.0.0.0:67` would hear real devices' DHCP requests, which is the
  rogue-DHCP risk. Decision: bind only to `DHCP_SERVER_IP` (Windows then delivers only that
  interface's broadcasts).
- VMware's DHCP service is running on the existing lab network, so DHCP needs its own isolated
  segment (SRS 4.6.2). That is planned for increment 7.

**Plan review:** seven design points (one row per address with a unique IP; bind to the server
IP; strict startup check with a restart after the first pool; RFC 2131 §4.3.2 REQUEST handling;
60–604800 s leases, 60 s offer hold, rate-limited exhaustion log; 300-byte padding; minimal relay
support). The user approved them all ("design point 1-7 good as is").

**Performance tracking matrix** (🟢 all pass, no regression · 🔴 fail → analysed)

| Inc | Tests | Cov | ruff | mypy | Zone | Notes |
|---|---|---|---|---|---|---|
| 0 | 203 / 203 | 92% | 0 | 0 | baseline | 37 routes; 5 adapters on the dev PC |
| 1 | 243 / 243 | 93% | 2 → 0 | 0 | 🟢 | Pool/reservation/lease rules; network/broadcast vs first/last host; lease 59/60/604800/604801; gateway inside range rejected; Cisco MAC form; **DB rejects two leases for one IP**. 40 new tests failed first |
| 2 | 260 / 260 | 93% | 0 | 0 | 🔴 → 🟢 | Codec tested on hand-assembled RFC bytes. 17 new tests failed first; then **one test bug**: it searched for `0xff` to find END, but the 255.255.255.0 mask contains `0xff`. Fixed in the test (walk the TLVs), not the codec |
| 3 | 278 / 278 | 94% | 0 | 0 | 🟢 | Allocator state machine: DORA, allocation order, all REQUEST cases, release/expiry, exhaustion log (59/61 s), **real-network IP → silence** (B). **Race test confirmed by line coverage** to hit the DB-rejection rollback (C). 18 new tests failed first |
| 4 | 290 / 290 | 93% | 0 | 0 | 🟢 | **Full DORA over real localhost UDP** (done-criterion). Bound address is not 0.0.0.0 (G). Refuses for a non-local IP or with no pool (B). Port in use → app keeps running. Malformed packets ignored. Background sweep. **Leases survive a restart** on a file DB (D). 12 new tests failed first |

**Not verified in this session:** behaviour on a real lab segment, and Windows broadcast send and
receive across a VMware adapter (checkpoint E, increment 7); the REST API, the Services screen DHCP
section and NFR-2 load (increments 5–7, next prompt).

**Human verification:** _(fill in: re-run `pytest tests/test_dhcp_*.py`; read `allocator.py`
`_request` against RFC 2131 §4.3.2; be ready to explain why the server binds to `DHCP_SERVER_IP`
instead of 0.0.0.0 on this PC, and why broadcast replies avoid raw sockets)_

---

## Entry template

```markdown
## P-0NN — <title>

**Context given:** files / SRS sections / issue
**Prompt:** > verbatim
**Plan returned:** (paste or summarize)
**Result:** files changed, tests added
**Verification:** commands run + results
**Issues found / corrections made by human:**
```
