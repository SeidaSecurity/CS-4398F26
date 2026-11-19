# ADR-0001: asyncio poll loop instead of APScheduler

- **Status:** Accepted (recorded retroactively, 2026-11-17)
- **Requirements:** R2.1; SRS 7.1 lists APScheduler

## Context
SRS 7.1 proposes APScheduler for poll intervals and retention jobs. The implementation
(`app/main.py::_run_monitoring`) uses a plain asyncio loop that runs `poll_all` in a worker thread
and then sleeps `POLL_INTERVAL_SECONDS`.

## Decision
Keep the asyncio loop for polling. It has no extra dependency, it shuts down cleanly through the
FastAPI lifespan, and it never runs two polling rounds at once.

## Consequences
- The interval is measured from the end of one round to the start of the next, so the period
  stretches with the round's duration.
- Retention jobs (R2.7, R4.5) need a scheduler too. If more than two periodic jobs appear,
  revisit APScheduler.
- **Action:** the default interval must be 60 s per R2.1. It is currently 30 s.
