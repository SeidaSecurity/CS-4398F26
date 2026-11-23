# ADR-0006: Authoritative DNS server design

- **Status:** Accepted (2026-11-19)
- **Requirements:** R5.1–R5.3 (Essential); R5.4–R5.6 (Desirable, deferred); NFR-3; SRS 5.3.1, 5.3.2, 6.1

## Context
SRS 4.5 requires the application itself to answer DNS queries for operator-defined zones, in
Python, conforming to RFC 1035 (SRS 6.1, 6.2). Track C had no implementation; the work was taken
over by another member (see the reassignment note in the prompt log).

## Decision
1. **Library:** `dnslib` for packet encoding and its threaded UDP/TCP server. Our code owns zone
   storage, validation, and every answering decision.
2. **Layout:** a separate subsystem package `app/dns/` (`zones.py` rules, `resolver.py`,
   `server.py`, `routes.py`), as SRS 5.3.2 asks; tables stay in `app/models.py` (new tables
   `dns_zones`, `dns_records`; no migration needed). `app.dns` cannot shadow a top-level `dns`
   library because it is namespaced under `app`.
3. **Data and rules:** record types A, AAAA, CNAME, PTR (reverse zones under `in-addr.arpa`). Names
   are lowercase, with no trailing dot, labels of 1–63 characters and at most 253 in total. TTL is
   30–604800 s per record, or the zone default (3600). A CNAME may not share a name with any other
   record, and may not sit at the apex (RFC 1034 §3.6.2). Every change bumps the zone's SOA serial.
4. **Answering:** the most specific matching zone wins. Authoritative answers set AA=1 and RA=0
   (no recursion). CNAMEs are followed inside local zones, at most 8 hops, after which the answer is
   SERVFAIL. A missing name returns **NXDOMAIN**. An existing name without the requested type
   (including the apex and empty non-terminals, RFC 8020) returns **NOERROR/no data**. Both put the
   zone's generated SOA in the authority section, with negative TTL 300 s (RFC 2308). An SOA query
   at the apex is answered. Names outside every local zone get **REFUSED**. Forwarding and caching
   (R5.4/R5.5) and DHCP registration (R5.6) are Desirable and come later.
5. **Freshness:** the resolver reads the zones from the database on every query, so API changes
   apply immediately with no cache to invalidate. NFR-3 (< 50 ms) is measured on the lab by
   `check-lab.ps1`. If it fails, an in-memory cache becomes its own increment.
6. **Runtime:** UDP and TCP on `DNS_HOST:DNS_PORT` (default `0.0.0.0:53`), started from the app
   lifespan only when `DNS_ENABLED=true`. A bind failure is logged with how to find the port's
   owner, and the rest of the app keeps running (SRS 5.3.1). The same rule now applies to the
   syslog listener (fixed in this work).

## Consequences
- The answering logic is a pure function, so it is tested with real DNS packets round-tripped
  through wire format, without sockets.
- On Windows, port 53 can be taken by Internet Connection Sharing or the Hyper-V/WSL networking
  services when those are on. During CML sessions they are off, so the port is normally free.

## Addendum — R5.4 upstream forwarding (proposed, pending PR review)

An optional `DNS_UPSTREAM_HOST` (literal IPv4) with `DNS_UPSTREAM_PORT` and
`DNS_FORWARD_TIMEOUT` enables outside-zone forwarding. The existing local-zone
resolver and negative answers remain authoritative and never reach the
upstream. Outside-zone queries are forwarded over UDP; truncation triggers a
TCP retry. Transaction IDs and question sections are validated, and failure
returns SERVFAIL without interrupting DNS or other subsystems. Leaving the
upstream unset preserves REFUSED for outside names.

This is R5.4 only: **R5.5 caching and R5.6 DHCP lease registration remain open**.
Run the offline tests and live acceptance check before approving this addendum.
