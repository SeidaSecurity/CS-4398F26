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

**Not verified in this session:** `check-lab.ps1` against a *running* lab (routers unreachable
during the session); the web UI start (Node still too old); `run-lab.ps1` past the placeholder
check (`.env.lab` not yet filled in); router-to-PC syslog through the firewall (no rule exists yet).

**Human verification:** _(fill in: after filling `.env.lab`, upgrading Node, adding the firewall
rules and starting the lab, run `run-lab.ps1` then `check-lab.ps1`; paste the table here and note
any rows that don't match)_

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

**Human verification:** _(fill in: admin and viewer logins on the lab; the viewer's 403 on a push
via /docs and its `access.denied` audit entry; AT-10 screenshots in
docs/verification/Acceptance-testSS/; be ready to explain the central policy and why the route
test walks OpenAPI instead of app.routes)_

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
