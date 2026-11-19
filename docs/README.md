# Project Documentation and Final Deliverables

The final archive (one submission per group) must contain the items below. This table shows where
each one lives and how complete it is.

| # | Deliverable | Location | Status |
|---|---|---|---|
| 1 | Prompts | [process/prompt-log.md](process/prompt-log.md), agent context in [../CLAUDE.md](../CLAUDE.md), process in [process/agentic-workflow.md](process/agentic-workflow.md) | Started; earlier sessions need reconstructing |
| 2 | Acceptance test execution with screenshots of every window and pop-up | [verification/acceptance-tests.md](verification/acceptance-tests.md), screenshots in `acceptance/screenshots/AT-xx/` | Cases written; need lab runs and screenshots |
| 3 | UML class diagram | [design/class-diagram.md](design/class-diagram.md) | Done for current code; update when Track C/auth land |
| 4 | System statechart diagrams | [design/statecharts.md](design/statecharts.md) | 6 implemented, 2 planned |
| 5 | Textual structure and critical algorithms | [design/architecture.md](design/architecture.md) | Done for Tracks A/B |
| 6 | Source code archive | `git archive --format=zip -o netmgr-src.zip HEAD` (excludes `node_modules`, `.venv`) | — |
| 7 | API docs (javadoc if Java) | Python: OpenAPI at `/docs` when running; optionally `pdoc app -o docs/api` | Optional for Python |
| 8 | Unit tests for Model/Controller classes | [../tests](../tests), plan in [verification/vv-plan.md](verification/vv-plan.md) | 23 tests, 80% coverage; gaps listed in the plan |
| 10 | Presentation | purpose, class diagram, statecharts, acceptance tests, screenshot of GitHub **Insights → Network** graph | Not started |

## Supporting documents
- [verification/traceability-matrix.md](verification/traceability-matrix.md): every SRS requirement → code → test → acceptance test.
- [improvement-plan.md](improvement-plan.md): prioritized fixes found in the audit.
- [contracts.md](contracts.md): cross-track API/schema contracts.
- [decisions/](decisions/): architecture decision records (deviations from the SRS).

## Rendering diagrams
The diagrams are Mermaid. GitHub renders them inline. For slides, paste a block into
<https://mermaid.live> and export SVG/PNG.
