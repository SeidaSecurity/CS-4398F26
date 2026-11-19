# ADR-0003: Pin paramiko below 5.0 for IOSv SSH compatibility

- **Status:** Accepted (2026-11-18), found during lab bring-up
- **Requirements:** R3.1, R3.2, R1.3 (all use SSH via Netmiko)

## Context
IOSv 15.9 in the CML lab offers only `diffie-hellman-group-exchange-sha1` and
`diffie-hellman-group14-sha1` for key exchange, and only `ssh-rsa` (SHA-1) host keys. paramiko 5.x,
which Netmiko 4.8 pulls in by default, has removed those algorithms entirely, not just disabled
them, so every SSH connection to the lab routers fails at key exchange. The unit tests use a fake
connector, so they could not detect this. Windows OpenSSH showed the same refusal.

## Decision
Pin `paramiko>=4.0,<5.0` in `pyproject.toml`. paramiko 4.0.0 still offers the SHA-1 key exchanges
and `ssh-rsa`. Netmiko declares paramiko 4 as a supported extra (`par4`). All 55 unit tests pass on 4.0.0.

## Rationale
This is a course project evaluated on its development process (MoT, design, verification and
validation) and run only against an isolated virtual lab. Production deployment is out of scope
(SRS 1.4). Downgrading one library to match the lab's device image is the smallest change that
unblocks validation, and is preferable to replacing the lab image late in the term.

## Consequences
- SHA-1 key exchange is weak. Acceptable only because the lab is isolated (SRS 6.2) and the
  system is not deployed to production.
- Revisit if the lab moves to an IOS XE image (e.g. Catalyst 8000v), which supports SHA-2
  algorithms. The pin can then be removed.
