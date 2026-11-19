# Agent context — Network Management Application (CS 4398 F26 capstone)

This file is loaded by coding agents (Claude Code, etc.) at the start of every session. It is the
standing context we give agents. Keep it short, true, and current; change it via PR like code.

## Source of truth

- Requirements: `SRS Requirements/SRS Network Management Application (Capstone).pdf`.
  Every change must trace to a requirement ID (`R<n>.<m>` or `NFR-<n>`).
- Traceability: `docs/verification/traceability-matrix.md`. Update the row for every
  requirement you touch (status, code, unit test, acceptance test).
- Contracts between tracks: `docs/contracts.md`. Do not change a frozen contract without a
  decision record in `docs/decisions/`.

## Architecture (MVC over a modular monolith)

- **Model** — `app/models.py` (SQLAlchemy tables), `app/schemas.py` (Pydantic DTOs).
- **Controller** — FastAPI routers (`app/main.py`, `app/monitoring.py`) plus domain logic
  (`app/config_service.py` — push/rollback/retrieve orchestration, `app/configuration.py` — Netmiko
  adapter and `DeviceError` hierarchy, `app/config_templates.py`, `app/poller.py`, `app/syslog.py`).
  Route handlers should stay thin: validate → call domain function → map result to HTTP.
- **View** — React app in `web/` (no business logic; it calls the REST API only, SRS 6.2).
- Device I/O sits behind protocols (`NetworkDeviceConnector`, `Probe`) so tests can inject fakes.
  Never call Netmiko/SNMP/ICMP directly from a route handler.

## Rules for agents

1. Before coding, state which requirement IDs the change satisfies and the acceptance criterion
   (from the SRS stimulus/response sequence) you will verify against.
2. Write or update a failing test first for new behavior; tests mock all device I/O (SRS 8.3).
3. Run before declaring done:
   `ruff check .` · `pytest --cov=app --cov-fail-under=70` · `mypy app --ignore-missing-imports`
   and, for UI changes, `npm run build` in `web/`.
4. Every state-changing endpoint must write an audit record (R4.4) and, once auth exists,
   reject the viewer role (R7.2).
5. Never put credentials in the database in plaintext, in API responses, or in commits (R1.4, NFR-6).
6. Operator-facing errors say what failed and what to do; never return raw exception text (SRS 5.3.3).
7. Do not add a package named `logging` (it shadows the standard library).
8. Follow MoT (`docs/process/agentic-workflow.md`): record a baseline, ONE capability per increment,
   label risky increments before starting, and report a tracking-matrix row per increment in chat.
   Do **not** edit `docs/process/prompt-log.md` unless the user explicitly asks; the team curates it.

## Commands

```sh
python -m pip install -e ".[dev]"
pytest --cov=app --cov-report=term-missing
ruff check .
cd web && npm install && npm run dev       # mock data; VITE_API_MODE=live for real backend
docker compose up --build                  # full stack with PostgreSQL
```

## Branches

`track-<a|b|c>/<issue-number>-<short-slug>` (SRS 10.1). PRs need CI green and one reviewer from
another track.
