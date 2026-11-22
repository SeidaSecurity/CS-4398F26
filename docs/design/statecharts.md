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

## 4. Rollback — R3.6 (`ConfigurationService.rollback`) — implemented

Same shape as §3. The target text comes from a stored `ConfigVersion`, the saved versions are
`pre_rollback` → `rollback`, and a missing device or version returns 404 before any state is entered.

## 5. Syslog message — R4.1, R4.2 (`app/syslog.py`) — implemented

```mermaid
stateDiagram-v2
    [*] --> Received : UDP datagram / TCP line on :514
    Received --> MatchRFC5424
    MatchRFC5424 --> Parsed : regex ok AND ISO timestamp valid AND PRI ≤ 191
    MatchRFC5424 --> MatchCiscoIOS : no match
    MatchRFC5424 --> Unparsed : timestamp invalid or PRI > 191
    MatchCiscoIOS --> Parsed : regex ok AND date valid AND PRI ≤ 191 / timestamp = receive time if '*' or '.'
    MatchCiscoIOS --> Unparsed : impossible date or PRI > 191
    MatchCiscoIOS --> MatchRFC3164 : no match
    MatchRFC3164 --> Parsed : regex ok AND date valid AND PRI ≤ 191
    MatchRFC3164 --> Unparsed : otherwise
    Parsed --> Stored : facility = PRI div 8, severity = PRI mod 8
    Unparsed --> Stored : keep raw, source = sender IP (else "unknown"), parsed=false
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

## 7. DHCP lease — R6.1, R6.3, R6.6, R6.7 (`app/dhcp/allocator.py`) — implemented

```mermaid
stateDiagram-v2
    [*] --> Free
    Free --> Offered : DISCOVER / pick reservation, else own lease, else lowest free; hold 60 s; OFFER
    Free --> Exhausted : DISCOVER, no free address / no reply; log (max 1 per pool per minute, R6.7)
    Exhausted --> Free : a lease is released or expires
    Offered --> Bound : REQUEST selecting our server, same address / ACK
    Offered --> Free : REQUEST selecting another server / no reply
    Offered --> Offered : REQUEST for a different address / NAK
    Offered --> Free : hold expires without REQUEST (address reusable)
    Bound --> Bound : REQUEST renewing (ciaddr = lease) / extend expiry, ACK
    Bound --> Bound : REQUEST init-reboot for its own address / ACK
    Bound --> Bound : DISCOVER again (e.g. reboot) / OFFER the same address
    Bound --> Free : RELEASE / delete lease (R6.6)
    Bound --> Free : expiry, removed by sweep (R6.6)
```

Requests are silent when the server has no pool for the subnet (no `giaddr` → the pool
containing `DHCP_SERVER_IP`; with `giaddr` → the pool containing it), so the server never
answers on a network it doesn't own. An init-reboot REQUEST for an address outside the subnet,
or one held by another client, gets NAK. One with no record of the client is ignored. Each
address can be in at most one lease (database unique constraint), so a concurrent claim fails
and the allocator moves to the next address.
Covered by `tests/test_dhcp_allocator.py`.

## 8. Operator session — R7.1, R7.2, R4.4 (`app/auth.py`, `app/auth_routes.py`) — implemented

```mermaid
stateDiagram-v2
    [*] --> Anonymous
    Anonymous --> Anonymous : any /api/v1 request / 401 "not logged in"
    Anonymous --> Anonymous : POST login, bad credentials / 401 generic, audit auth.login failed
    Anonymous --> SignedIn : POST login, valid and enabled / session row + HTTP-only cookie, audit succeeded
    state SignedIn {
        [*] --> Admin : role = admin
        [*] --> Viewer : role = viewer
        Admin --> Admin : any request / allowed
        Viewer --> Viewer : GET / allowed
        Viewer --> Viewer : non-GET or /users / 403, audit access.denied refused
        Admin --> Viewer : an admin changes the role (next request)
        Viewer --> Admin : an admin changes the role (next request)
    }
    SignedIn --> Anonymous : POST logout / session row deleted, cookie cleared, audit auth.logout
    SignedIn --> Anonymous : 8 h after login / session expired
    SignedIn --> Anonymous : account disabled by an admin / takes effect on the next request
```

The role is re-read from the database on every request (`resolve_session`), which is why role
changes and disabling take effect immediately. A wrong password, an unknown user and a disabled
user all produce the **same** 401 body (SRS 3.1.1). An idle timeout (R7.5, Desirable) is not
implemented; sessions end 8 hours after login (`SESSION_HOURS`).
Covered by `tests/test_auth_api.py`, `tests/test_access_policy.py`, `tests/test_auth.py`.

## 9. User account — R7.4 (`auth.create_user`, `auth.update_user`) — implemented

```mermaid
stateDiagram-v2
    [*] --> ActiveViewer : created by an admin (role viewer)
    [*] --> ActiveAdmin : created by an admin (role admin), or bootstrap from env when no users exist
    ActiveViewer --> ActiveAdmin : role -> admin / audit user.update
    ActiveAdmin --> ActiveViewer : role -> viewer [another active admin exists] / audit
    ActiveAdmin --> ActiveAdmin : role -> viewer or disable [last active admin] / 409 refused
    ActiveViewer --> Disabled : disable / sessions stop working, audit
    ActiveAdmin --> Disabled : disable [another active admin exists] / audit
    Disabled --> ActiveViewer : enable (role viewer)
    Disabled --> ActiveAdmin : enable (role admin)
```

There is no "deleted" state: accounts are disabled, so audit records always name a real user.
A password reset (policy-checked) is a self-transition in either active state.
Covered by `tests/test_users_api.py` and `test_r7_4_bootstrap_*`.
