# Verification and Validation Plan

**Verification** asks whether we built the system right, measured against the SRS and the design.
**Validation** asks whether we built the right system, measured against what an operator needs
(the SRS stimulus/response sequences). Both are tied to requirement IDs through the
[traceability matrix](traceability-matrix.md).

## 1. Levels

| Level | What | Tooling | Where it runs | Gate |
|---|---|---|---|---|
| Static | Lint, formatting, type checks | `ruff`, `mypy`, `tsc` (via `npm run build`) | CI on every PR | Must pass (mypy reached 0 errors on 2026-11-17 and is now blocking) |
| Unit | One domain function or class, all device I/O faked | `pytest` | CI | Must pass; coverage ≥ 70% (`--cov-fail-under=70`) |
| API / integration | Route → domain → in-memory SQLite, fake connector/probe | `pytest` + FastAPI `TestClient` | CI | Must pass |
| Lab integration | Real Postgres plus GNS3 routers, syslog from IOS, `dig`/`dhcping` | Manual or scripted against the lab | Weekly Friday lab session (SRS 10.2) | Each Essential FR passes once before M2 |
| Acceptance | Operator-level scenarios through the UI, with screenshots | [acceptance-tests.md](acceptance-tests.md) | Before each milestone demo | All Essential ATs pass for M2 |
| Performance | NFR-1..4 | Scripts in `lab/load/` (to be written) | Week 11–13 | Measured numbers recorded in the RTM |

## 2. Designing unit tests systematically

Don't pick test cases ad hoc. For each function under test, derive cases with these techniques
and name the technique in the test's docstring:

1. **Equivalence partitioning.** Split each input into classes that should behave the same.
   Example, `render_template`: all placeholders supplied / one missing / one extra / malformed braces.
2. **Boundary-value analysis.** Test at and around each limit. Examples: `ssh_port` = 0, 1,
   65535, 65536; syslog PRI = 191 and 192; consecutive failures = 1 and 2 (R2.5 threshold).
3. **State-transition coverage.** Cover every transition in the statecharts
   ([../design/statecharts.md](../design/statecharts.md)) at least once, plus one invalid event
   per state. Example, the device state machine: up→up, up(0)→up(1), up(1)→down, down→down
   (no duplicate alert), down→up (alert resolved).
4. **Error guessing / fault injection.** The fake connector raises on retrieve, push, or
   post-push retrieve; the fake probe raises; the DB raises `IntegrityError`.

Every test traces to a requirement in its name or docstring, for example
`def test_r2_5_alert_raised_on_second_consecutive_failure():`.

## 3. Current unit-test gaps (priority order)

| Module | Coverage | Missing cases |
|---|---|---|
| `app/probes.py` | 27% | SNMP response parsing, counter-delta and wrap math, uptime reset, ICMP-ok + SNMP-fail path (refactor so the pure math is testable without the network) |
| `app/configuration.py` | 53% | `EnvironmentCredentials`: invalid JSON, non-object, missing device, missing password, optional secret |
| `app/main.py` push | 83% | Failure **after** apply (post-push retrieve raises); unknown device id; duplicate ids de-duplicated |
| `app/poller.py` | 92% | Probe raises → counted as failure; down→down produces no second alert; interface replacement |
| `app/syslog.py` | 86% | `%`/`_` in search text; `since > until` → 422; TCP multi-line framing |
| `web/src/lib/diff.ts` | none | Insert/delete/change rows; empty input (add Vitest) |

## 4. Validation (acceptance)

Acceptance tests are written from the SRS stimulus/response sequences: one AT per feature, plus one
per alternate outcome (a/b/c branches). Each AT records preconditions, numbered steps, the expected
result per step, the actual result, pass/fail, and a screenshot of **every window and pop-up**
(an instructor deliverable). Run them against the live backend (`VITE_API_MODE=live`), never
against mock data.

## 5. Process gates (Definition of Done, SRS 10.3)

A PR merges only when:

- [ ] It names the requirement IDs it addresses (PR template).
- [ ] New behavior has a unit test written first or alongside; coverage is not reduced.
- [ ] CI is green (ruff, pytest with coverage gate, web build).
- [ ] The RTM row is updated (status, code, test).
- [ ] An API or schema change is documented in `docs/contracts.md` or `docs/decisions/`.
- [ ] A member from another track has reviewed it.
- [ ] For a feature-complete FR, the matching AT passed on the lab, with screenshots saved under
      `docs/acceptance/screenshots/AT-xx/`.

## 6. Defect tracking

Log a defect found during review or lab testing as a GitHub issue labeled `defect` and
`R<n>.<m>`. Its fix PR must add a regression test that fails before the fix.
