# Disciplined Agentic Development: Module of Thought (MoT)

The instructor will check that we used a disciplined agentic process (MoT, as taught in class),
what context we gave the agents, and whether verification was systematic. This file shows how we
apply each MoT component to this project. The evidence for each is in the linked files and in the
prompt log.

## MoT components and how we apply them

| MoT component | What it means | How we do it here | Evidence |
|---|---|---|---|
| **1. Explicit context loading ("Prompt 0")** | A persistent context document loaded at the start of every session, so knowledge doesn't drift between sessions | `CLAUDE.md` is loaded automatically by the agent. It holds the SRS location, the MVC layering, agent rules, and commands. The prompt also pastes the specific SRS requirement text | [../../CLAUDE.md](../../CLAUDE.md), the "Context given" field of each prompt-log entry |
| **2. Quantitative baseline** | A verifiable starting point measured before any change, so degradation is detectable | Before each session, record the **test count, pass count, line coverage, ruff errors, mypy errors, and tsc result** | The baseline row (Inc 0) of each tracking matrix in the prompt log |
| **3. Incremental modules, ONE capability each** | Each increment adds exactly one capability, mapped to one requirement | One increment per requirement ID; one test (or test group) named after it (`test_r3_5_…`); full gate after every increment | Increment tables in the prompt log; requirement-named tests |
| **4. A priori critical checkpoints** | Risky increments are labeled **before** execution, with the specific risk and a prepared mitigation | Plan tables mark ⚠ increments: refactors that must preserve behavior, API contract changes, transaction-order changes, security changes | The "Checkpoint" column in the plan; P-002 Inc 4 and Inc 5 |
| **5. Performance tracking matrix** | A metric recorded per increment, with Green/Yellow/Red zones | Per increment: tests passed/total, coverage %, ruff, mypy. **Green**: all pass, coverage ≥ baseline, no new lint/type errors. **Yellow**: all pass but coverage dropped or warnings appeared. **Red**: any test or gate fails → stop and isolate | Tracking matrix in each prompt-log entry |
| **6. Isolation testing protocol** | Specific debugging procedure per checkpoint | (a) Behavior-preserving refactor: the old tests are the oracle and must pass **unchanged**. (b) New behavior: the new test must **fail on the old code** (`git stash push app/` → run → `git stash pop`) and pass on the new. (c) Contract change: back end tests, then `tsc` on the front end, before moving on | P-002 fail-before evidence; Inc 4 oracle run |
| **7. Degradation analysis protocol** | Systematic root-cause procedure when a metric drops | On Red: 1) identify the increment (only one changed); 2) read the failing assertion. Is it an *intended* contract change or a regression? 3) If intended, update the test **and** `docs/contracts.md` in the same increment; 4) if a regression, revert that increment and re-plan; 5) record the cause in the prompt log | P-002 Inc 5 (two intended failures documented) |
| **8. Progressive complexity** | Simple → complex, with explicit dependencies | Low-risk one-liners first (Inc 1–3), then the refactor (Inc 4) that the classification work (Inc 5–6) depends on, then typing cleanup (Inc 7) | P-002 increment order |

## The per-increment loop

| Step | Who | Output kept as evidence |
|---|---|---|
| 1. **Specify** | Human | Issue titled with requirement IDs and acceptance criteria from the SRS stimulus/response sequence |
| 2. **Plan + label checkpoints** | Agent (plan mode), human approves | Increment table with ⚠ checkpoints and risks, pasted into the prompt log |
| 3. **Test first** | Agent | Requirement-named tests that fail on the old code |
| 4. **Implement one capability** | Agent | Smallest change that makes the tests pass |
| 5. **Measure** | Agent runs, human reads | One tracking-matrix row: tests, coverage, ruff, mypy, tsc |
| 6. **Review** | Human from another track (+ `/code-review`) | PR comments resolved |
| 7. **Validate** | Human on the lab | Acceptance-test result and screenshots; RTM row ✅ |
| 8. **Record** | Human | Prompt-log entry including **Human verification**; ADR if a contract changed |

### Rules
- **One requirement per branch/PR** (`track-b/<issue>-<slug>`), so the git Network graph shows increments.
- **Agents never mark their own work done.** A human reads the test output and the diff, and
  records that in the prompt log's *Human verification* section.
- **Don't accept code you can't explain.** The instructor will ask about generated code and tests.

## Prompt template

```text
Context (Prompt 0): CLAUDE.md, SRS §4.3 (pasted below), docs/contracts.md.
Baseline: <tests passed/total, coverage %, ruff, mypy> - measure first if unknown.
Requirement: R3.5 - "The application shall report the result of a push per device and shall not
abort remaining pushes because one device failed." SRS 4.3.4 step 5 distinguishes (b) rejected
and (c) unreachable.
Task: Plan first, no code. Break into increments of ONE capability each; mark critical
checkpoints with the risk and the isolation test you will use. Wait for approval.
Constraints: device I/O only via NetworkDeviceConnector; tests use FakeConnector; thin routes;
audit every outcome; operator-facing errors say what failed and what to do.
Done when: new tests fail before / pass after; tracking row is Green; RTM row updated.
```
