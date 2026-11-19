# Prompt Log (Deliverable 1)

One entry per meaningful agent session. Keep the actual prompt text; summarize the response.
Earlier work (before 2026-11-17) was not logged consistently. Reconstruct what you can from
commit history and chat exports, and mark those entries "reconstructed".

| # | Date | Author | Agent / model | Requirement(s) | Commit / PR |
|---|---|---|---|---|---|
| P-001 | 2026-11-17 | Justin | Claude Code (Opus 5.5) | process, all | (uncommitted) |
| P-002 | 2026-11-17 | Justin | Claude Code (Opus 5.5) | R2.1, R4.3, R4.4, R3.2, R3.5, R1.2, 5.3.3, 10.4 | (uncommitted) |

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
