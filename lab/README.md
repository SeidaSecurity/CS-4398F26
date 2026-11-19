# Virtual Lab (SRS Appendix II)

Rebuilds the test network from a clean checkout. Device images come from each member's own Cisco
Modeling Labs (CML) subscription, used for non-commercial testing only. **Images are never
committed** (`.gitignore` blocks `*.qcow2`, `*.iso`, and `lab/images/`).

## Topology (Tracks A and B)

```
   Windows PC 192.168.198.1 (VMnet8)   app: API :8000, syslog :514
   CML VM     192.168.198.128          CML web UI (VMware DHCP)
              |
     [External Connector: System Bridge]  -- VMware NAT network 192.168.198.0/24
              |
         [Unmanaged switch]
      /     |      |      \
 ios-lab-1 ios-lab-2 ios-lab-3 ios-lab-4
   .11       .12       .13      .14 (left stopped: "unreachable node", AT-03)

 Data link: ios-lab-1 Gi0/1 10.0.12.1/30 <-> ios-lab-2 Gi0/1 10.0.12.2/30
            (shut / no shut it to generate syslog and interface-status changes)
```

Track C will add hosts and switches for DHCP/DNS later (SRS 8.2).

## Building the lab in CML

The lab platform is CML ([ADR-0004](../docs/decisions/0004-cml-as-lab-platform.md)). The SRS
originally named GNS3. One team member hosts the lab, and the others develop against fake devices
and join lab sessions.

1. In CML: add 4 × **IOSv** nodes, 1 × **unmanaged switch**, and 1 × **External Connector**.
   Set the connector to **System Bridge** (`bridge0`), so the routers share an L2 segment with the
   network the CML VM's NIC is on.
2. The CML VM's adapter is on VMware **NAT (VMnet8)**, 192.168.198.0/24. Windows is `192.168.198.1`,
   VMware's gateway is `.2`, and VMware DHCP hands out `.128` and up (the CML UI got `.128`).
   Routers use static `.11`–`.14`, outside the DHCP range. Don't use Bridged mode: it would put the
   routers on your real home or campus network (SRS 6.2).
3. Paste `configs/ios-lab-N.cfg` into each router's console, replacing the placeholders. Leave
   ios-lab-4 stopped.
4. Export the lab topology (`Lab → Download lab` YAML) to `lab/cml-topology.yaml` and commit it.
   The YAML references image names only, not the images themselves.

## Run natively on Windows (CML sessions)

CML needs VMware nested virtualization, which stops working while WSL2/Hyper-V is on, and Docker
Desktop needs WSL2. So during CML sessions the app runs **natively on Windows**, not in Docker.
Docker Compose stays the packaging for Linux hosts (SRS 5.3.4).

**Prerequisites:** Python ≥ 3.11 and Node ^20.19 or ≥ 22.12 on PATH; WSL/Hyper-V **off**; CML lab started.

**1. Create your settings file** (git-ignored; values must match the router configs):
```powershell
Copy-Item .env.lab.example .env.lab
notepad .env.lab        # replace every REPLACE_WITH_* value
```
`ADMIN_USERNAME` / `ADMIN_PASSWORD` create the first admin account on startup, but only while no
users exist (R7.4, ADR-0005). The password must be 8-64 characters, not a common password, and
not the username. `run-lab.ps1` checks this before starting, because a rejected password would
otherwise leave nobody able to log in.

**2. Allow syslog through the firewall** (once, in PowerShell **as Administrator**). VMware's
adapters are usually on the *Public* profile, so the rules must cover it:
```powershell
New-NetFirewallRule -DisplayName "netmgr syslog UDP 514" -Direction Inbound -Protocol UDP -LocalPort 514 -Action Allow -Profile Any
New-NetFirewallRule -DisplayName "netmgr syslog TCP 514" -Direction Inbound -Protocol TCP -LocalPort 514 -Action Allow -Profile Any
```

**3. Start everything:**
```powershell
powershell -ExecutionPolicy Bypass -File scripts\run-lab.ps1
```
The script creates `.venv` if needed, installs the project, and checks Python, Node, paramiko < 5
(ADR-0003), that `.env.lab` has no placeholders left, and that `ADMIN_PASSWORD` meets the app's
password policy. It never prints `.env.lab` values. Then it
starts the API here and the live web UI in a second window. Options: `-CheckOnly` (run the checks,
start nothing), `-NoWeb` (API only, e.g. while Node is too old), `-Reinstall`.
`-ExecutionPolicy Bypass` is needed because Windows blocks `.ps1` scripts by default.

**4. Log in** with `ADMIN_USERNAME` / `ADMIN_PASSWORD`. Create more accounts (for example a
read-only viewer) on the **Accounts** screen.

**5. Register the routers** on the Devices screen: names `ios-lab-1`…`ios-lab-4` (exactly the keys
in `.env.lab`), IPs `192.168.198.11`…`.14`.

**6. Smoke-test**, in a second terminal while the app runs:
```powershell
powershell -ExecutionPolicy Bypass -File scripts\check-lab.ps1
```
It logs in as the `.env.lab` admin (values are never printed), then prints a pass/fail table: API
health, the admin login, a syslog round trip (sent to 127.0.0.1), the firewall rules, ping and TCP 22 to each router, and the app's own up/down state for each registered router.
"PASS" means *as expected*, so ios-lab-4 passes when it is unreachable. The local syslog test cannot
prove the routers' syslog gets through, which is why the firewall rows exist; still do the manual
syslog row in the table below.

Notes: the database is `network_manager.db` in the repo root (SQLite, git-ignored). The script
always starts from the repo root, so it is never created anywhere else. Delete the file to start fresh.

### DNS service (R5.1–R5.3, ADR-0006)

**Enable it:** in `.env.lab`, set `DNS_ENABLED=true` (`DNS_HOST=0.0.0.0`, `DNS_PORT=53`) and
restart `run-lab.ps1`. If port 53 is taken, the API window logs the cause, DNS stays off, and the
rest of the app keeps running. Find what holds the port with
`Get-NetUDPEndpoint -LocalPort 53 | Select-Object LocalAddress, OwningProcess`. Internet
Connection Sharing and the Hyper-V/WSL networking services can take port 53 when they're on.

**Create the lab records** on the **Services** screen (as admin). `check-lab.ps1` expects these:

| Zone | Record name | Type | Value |
|---|---|---|---|
| `lab.local` | `r1` | A | `192.168.198.11` |
| `198.168.192.in-addr.arpa` | `11` | PTR | `r1.lab.local` |

**Query it from Windows:**
```powershell
Resolve-DnsName r1.lab.local -Server 127.0.0.1 -DnsOnly                  # A record
Resolve-DnsName 192.168.198.11 -Server 127.0.0.1 -DnsOnly                # reverse (PTR)
Resolve-DnsName no-such-host.lab.local -Server 127.0.0.1 -DnsOnly        # NXDOMAIN error
.venv\Scripts\python scripts\dns_probe.py r1.lab.local --repeat 5         # shows AA flag + timing
```
`Resolve-DnsName` doesn't show the AA (authoritative) flag. `dns_probe.py` does, and
`check-lab.ps1` uses it for its four DNS rows (answer, NXDOMAIN, PTR, NFR-3 response time).

**From routers or other lab hosts** (optional), point them at `192.168.198.1` and allow inbound
UDP/TCP 53 in the firewall (Administrator):
```powershell
New-NetFirewallRule -DisplayName "netmgr DNS UDP 53" -Direction Inbound -Protocol UDP -LocalPort 53 -Action Allow -Profile Any
New-NetFirewallRule -DisplayName "netmgr DNS TCP 53" -Direction Inbound -Protocol TCP -LocalPort 53 -Action Allow -Profile Any
```
On an IOSv router: `conf t` → `ip domain lookup` → `ip name-server 192.168.198.1` → `end`, then
`ping r1.lab.local`.

### Alternative: Docker (Linux host, or an Ubuntu VM next to CML)
Put the same settings in `.env`, then run `docker compose up --build` and
`cd web && VITE_API_MODE=live npm run dev`.

## Smoke test (run before any acceptance test)

| Check | Command / action | Expected |
|---|---|---|
| L3 reachability | `ping 192.168.198.11` from Windows | Replies |
| SSH | `ssh -o KexAlgorithms=+diffie-hellman-group14-sha1 -o HostKeyAlgorithms=+ssh-rsa lab@192.168.198.11` (IOSv offers only SHA-1 algorithms; Windows OpenSSH needs these flags) | Router prompt |
| SNMP (optional, from WSL) | `snmpwalk -v2c -c <community> 192.168.198.11 1.3.6.1.2.1.2.2.1.2` | Interface names |
| Polling | Open the dashboard and wait 60 s | ios-lab-1..3 **up**; ios-lab-4 **down** after 2 polls |
| Syslog | On ios-lab-1: `conf t` → `int gi0/1` → `shut` → `no shut` | Link up/down messages appear on the Logs page |
| Config retrieve | History → retrieve | A version is saved |

## Troubleshooting

- **DNS rows fail in check-lab with "no reply":** `DNS_ENABLED=true` missing from `.env.lab` (restart after adding it), or port 53 taken (see "DNS service" above). **"NXDOMAIN" instead of an answer:** the zone or record hasn't been created on the Services screen.
- **No syslog arriving:** allow inbound UDP/TCP 514 in Windows Defender Firewall (step 2 above).
- **Every router unreachable, even from `ping.exe`:** the lab isn't running or reachable. Check
  that CML and the routers are started and that WSL/Hyper-V is off (a
  `vEthernet (WSL ...)` adapter appearing is a sign it's on).
- **Windows can ping a router but the app shows it down:** `check-lab.ps1` flags this. Natively,
  check the API window for errors; in Docker, unprivileged ICMP may be blocked in the container
  (`docker compose logs api`).
- **SSH "no matching key exchange method":** IOSv offers only SHA-1 algorithms. For your own ssh client, add `-o KexAlgorithms=+diffie-hellman-group14-sha1 -o HostKeyAlgorithms=+ssh-rsa`. The app needs paramiko < 5 (pinned in `pyproject.toml`, ADR-0003).
