# ADR-0007: DHCP server design

- **Status:** Accepted (2026-11-20). Increments 1–4 implemented; API, screen and lab are next.
- **Requirements:** R6.1–R6.6 (Essential), R6.7 (Desirable), NFR-2; SRS 4.6.2, 5.3.1, 6.1, 6.2

## Context
SRS 4.6 requires the application to issue and track DHCP leases, in Python, conforming to
RFC 2131 (SRS 6.1). SRS 6.2 anticipated that raw sockets might be hard and allowed a fallback.
The development PC is **multi-homed**: besides the lab adapters it has a real network adapter
(`192.168.1.49`). The current CML lab network (VMware NAT) already runs VMware's own DHCP, which
SRS 4.6.2 forbids on the same broadcast domain.

## Decision
1. **Package** `app/dhcp/`: `pools.py` (rules), `packet.py` (codec), `allocator.py` (state
   machine), `server.py` (UDP), plus `routes.py` later. New tables `dhcp_pools`,
   `dhcp_reservations`, `dhcp_leases`.
2. **No raw sockets, no scapy.** A standard UDP socket with `SO_BROADCAST`. Replies follow RFC 2131
   §4.1: a relayed request goes back to `giaddr:67`, a renewal is unicast to `ciaddr`, and everything
   else (including NAKs) is broadcast to `255.255.255.255:68`. A server only needs raw sockets to
   unicast to a client with no address yet; broadcasting avoids that.
3. **Own codec** (`struct`): the 236-byte BOOTP header, the magic cookie, and options 1, 3, 6, 12, 15,
   50, 51, 53, 54, 55, 61, 255. RFC 3396 split options are joined, and replies are padded to 300 bytes.
4. **Safety (rogue-DHCP prevention):**
   - DHCP starts only if `DHCP_ENABLED=true`, `DHCP_SERVER_IP` is an address of this computer, and a
     pool contains it.
   - The socket is bound to **`DHCP_SERVER_IP`, not `0.0.0.0`**. On Windows such a socket receives
     only that interface's broadcasts, so the real network is never heard.
   - Every packet is matched to a pool: by `giaddr` if relayed, else by `DHCP_SERVER_IP`. No pool
     means no reply.
   - `DHCP_BIND_HOST=0.0.0.0` exists only for a single-interface Linux host (the Ubuntu-VM
     fallback), and it logs a warning.
5. **Allocation:**
   - Order: the MAC's reservation, then its existing lease, then the lowest free address in the range.
   - Offers are held 60 s. REQUEST handling follows RFC 2131 §4.3.2 (selecting, init-reboot,
     renewing). DECLINE and INFORM are logged and ignored.
   - **One row per address with a unique IP:** a concurrent claim fails in the database, is rolled
     back, and the next address is tried. Rollback is used instead of SAVEPOINTs, which the SQLite
     driver handles unreliably.
6. **Lifetimes:**
   - Lease time is 60–604800 s per pool.
   - Released or expired leases free their address, swept every 60 s.
   - Leases live in the database, so they survive restarts (R6.5).
   - An exhausted pool sends no offer and writes one warning `LogRecord` per pool per minute (R6.7).
7. **Runtime:** started from the app lifespan; a bind failure or a failed safety check is logged
   and the rest of the app keeps running (SRS 5.3.1).

## Consequences
- Every protocol decision is in our code and unit-testable: the codec on bytes, and the allocator
  as a pure state machine with an injectable clock.
- After creating the **first** pool, the app must be restarted for DHCP to start (strict startup
  check). Later pool changes apply immediately.
- **Windows broadcast behaviour on the real lab segment is still unproven.** It is checked by a
  time-boxed spike in increment 7. If it fails, the fallback is to run the stack in an Ubuntu VM
  on the isolated segment (SRS 6.2), recorded as an amendment to this ADR.
- The lab needs an **isolated segment without VMware DHCP** (SRS 4.6.2), to be set up in increment 7.
