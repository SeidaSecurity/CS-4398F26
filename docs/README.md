# Project Documentation and Final Deliverables

The final archive (one submission per group) must contain the items below. This table shows where
each one lives and how complete it is.

| # | Deliverable | Location | Status |
|---|---|---|---|
| 1 | Prompts | [process/prompt-log.md](process/prompt-log.md), agent context in [../CLAUDE.md](../CLAUDE.md), process in [process/agentic-workflow.md](process/agentic-workflow.md) | P-001–P-008 logged; human-verification notes to fill in |
| 2 | Acceptance test execution with screenshots of every window and pop-up | [verification/acceptance-tests.md](verification/acceptance-tests.md), screenshots in `verification/Acceptance-testSS/` | All cases unblocked; first screenshots taken (AT-01–06, AT-10); per-step screenshots, Actual and P/F still to record |
| 3 | UML class diagram | [design/class-diagram.md](design/class-diagram.md) | Done for all tracks: platform/monitoring, configuration/logging, auth, DNS and DHCP |
| 4 | System statechart diagrams | [design/statecharts.md](design/statecharts.md) | 10 implemented: reachability, alerts (down and CPU), push, rollback, syslog, templates, DHCP lease, operator session, user account, add device with connection test |
| 5 | Textual structure and critical algorithms | [design/architecture.md](design/architecture.md) | Done for all tracks: §2.1–2.13 incl. access decision, DNS resolution, DHCP allocation, credential protection, connection test, LCS diff |
| 6 | Source code archive | `git archive --format=zip -o netmgr-src.zip HEAD` (excludes `node_modules`, `.venv`) | — |
| 7 | API docs (javadoc if Java) | Python: OpenAPI at `/docs` when running; optionally `pdoc app -o docs/api` | Optional for Python |
| 8 | Unit tests for Model/Controller classes | [../tests](../tests), plan in [verification/vv-plan.md](verification/vv-plan.md) | 408 tests, 95% coverage across all tracks, incl. the route-coverage test for the access policy and diff parity fixtures |
| 10 | Presentation | purpose, class diagram, statecharts, acceptance tests, screenshot of GitHub **Insights → Network** graph | Not started |

## Supporting documents
- [verification/traceability-matrix.md](verification/traceability-matrix.md): every SRS requirement → code → test → acceptance test.
- [improvement-plan.md](improvement-plan.md): prioritized fixes found in the audit.
- [contracts.md](contracts.md): cross-track API/schema contracts.
- [decisions/](decisions/): architecture decision records (deviations from the SRS).

## Rendering diagrams
The diagrams are Mermaid code blocks. GitHub and VS Code's Markdown preview (with a Mermaid
extension) render them inline. For slides, copy one block's contents (without the
```` ```mermaid ```` fences) into <https://mermaid.live> and use **Actions → PNG/SVG**. To render
every diagram in a file at once, run
`npx -y @mermaid-js/mermaid-cli -i docs/design/statecharts.md -o docs/design/img/statecharts.md -e png`;
it writes `statecharts-1.png`, `statecharts-2.png`, … (one per diagram) into `docs/design/img/`.
