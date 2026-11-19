# System Statechart Diagrams

Each diagram models behavior that exists in the code (citing the function) or behavior the SRS
requires that is still **planned**. Use each transition as a test case (see `vv-plan.md` §2.3).

## 1. Device reachability — R2.2, R2.5 (`app/poller.py::poll_device`) — implemented

```mermaid
stateDiagram-v2
    [*] --> Unpolled : device created
    Unpolled --> Up : poll ok
    Unpolled --> Suspect : poll fails  [failures=1, state stored as "up"]
    Up --> Up : poll ok  [failures=0]
    Up --> Suspect : poll fails  [failures=1]
    Suspect --> Up : poll ok  [failures=0]
    Suspect --> Down : poll fails  [failures=2] / raise Alert
    Down --> Down : poll fails  [failures++] / no new alert
    Down --> Up : poll ok  [failures=0] / resolve open Alerts
    Up --> [*] : device deleted
    Suspect --> [*] : device deleted
    Down --> [*] : device deleted
```

`Suspect` is a derived state: the DB stores `state="up"` with `consecutive_failures=1`. A probe
exception counts as a failed poll.

## 2. Alert lifecycle — R2.5 — implemented

```mermaid
stateDiagram-v2
    [*] --> Open : device enters Down (at most one open alert per outage)
    Open --> Resolved : next successful poll / resolved_at = now
    Resolved --> [*]
```

## 3. Per-device configuration push — R3.1, R3.2, R3.5 (`app/config_service.py::ConfigurationService._apply_change`) — implemented

```mermaid
stateDiagram-v2
    [*] --> Pending
    Pending --> NotFound : device id not in inventory
    Pending --> CapturingBefore
    CapturingBefore --> Unreachable : DeviceUnreachableError
    CapturingBefore --> CredentialProblem : DeviceCredentialError
    CapturingBefore --> Failed : unexpected exception
    CapturingBefore --> Applying : save pre_push version, audit "started", COMMIT
    Applying --> Rejected : DeviceRejectedError (IOS "% Invalid input…")
    Applying --> Unreachable : session lost
    Applying --> Failed : unexpected exception
    Applying --> CapturingAfter
    CapturingAfter --> Unverified : read-back fails (change IS on the device), audit "unverified"
    CapturingAfter --> Succeeded : save post_push version, audit "succeeded"
    NotFound --> [*]
    Unreachable --> [*]
    CredentialProblem --> [*]
    Rejected --> [*]
    Failed --> [*]
    Unverified --> [*]
    Succeeded --> [*]
```

Each final state is the `status` value returned for that device. Every terminal state continues
with the next device (R3.5). The COMMIT before `Applying` guarantees that the pre-change snapshot
survives a failure later in the sequence. Covered by `test_r3_5_*`, `test_5_3_3_*`, and
`test_push_saves_versions_*`. (Before P-002, the read-back failure was reported as "failed".)

## 4. Rollback — R3.6 (`restore_configuration`) — implemented

Same shape as §3. The target text comes from a stored `ConfigVersion`, the saved versions are
`pre_rollback` → `rollback`, and a missing device or version returns 404 before any state is entered.

## 5. Syslog message — R4.1, R4.2 (`app/syslog.py`) — implemented

```mermaid
stateDiagram-v2
    [*] --> Received : UDP datagram / TCP line on :514
    Received --> MatchRFC5424
    MatchRFC5424 --> Parsed : regex ok AND ISO timestamp valid AND PRI ≤ 191
    MatchRFC5424 --> MatchRFC3164 : no match
    MatchRFC5424 --> Unparsed : timestamp invalid or PRI > 191
    MatchRFC3164 --> Parsed : regex ok AND date valid AND PRI ≤ 191
    MatchRFC3164 --> Unparsed : otherwise
    Parsed --> Stored : facility = PRI div 8, severity = PRI mod 8
    Unparsed --> Stored : keep raw, source="unknown", parsed=false
    Stored --> Purged : older than retention  (R4.5 — planned)
    Stored --> [*]
    Purged --> [*]
```

## 6. Configuration template render — R3.7 — implemented

```mermaid
stateDiagram-v2
    [*] --> Editing
    Editing --> Invalid : stray {{ or }}  /  missing value  /  unused value
    Invalid --> Editing : operator fixes
    Editing --> Rendered : all placeholders supplied
    Rendered --> ConfirmPush : Push clicked (confirmation dialog)
    ConfirmPush --> Editing : cancel
    ConfirmPush --> [*] : confirm → §3 per device
```

## 7. DHCP lease — R6.1, R6.5, R6.6 — **planned (Track C)**

```mermaid
stateDiagram-v2
    [*] --> Free
    Free --> Offered : DISCOVER, address selected (reservation first, else next free)
    Offered --> Free : offer timeout without REQUEST
    Offered --> Bound : REQUEST matches / ACK, persist lease
    Bound --> Bound : renew REQUEST / extend expiry
    Bound --> Free : RELEASE or expiry
    Free --> Exhausted : DISCOVER with no free address / log (R6.7)
```

## 8. Operator session — R7.1, R7.2, R7.5 — **planned (Track A)**

```mermaid
stateDiagram-v2
    [*] --> Anonymous
    Anonymous --> Anonymous : bad credentials / generic error, audit failure
    Anonymous --> Authenticated : good credentials / audit login
    state Authenticated {
        [*] --> Admin
        [*] --> Viewer
        Viewer --> Viewer : write request / 403, audit refusal
    }
    Authenticated --> Anonymous : logout or idle timeout (R7.5)
```
