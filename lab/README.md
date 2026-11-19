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

## Option A: run the lab in CML (fewest steps)

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

## Option B: run the lab in GNS3 (what SRS 8.1 names)

1. Install GNS3 all-in-one and the **GNS3 VM** (VMware Workstation or VirtualBox).
2. Copy the IOSv image out of your CML reference-platform ISO:
   `virl-base-images/iosv-*/vios-adventerprisek9-m*.qcow2`, stored outside the repo or in `lab/images/`.
3. In GNS3, import the **Cisco IOSv** appliance template (marketplace), point it at the qcow2,
   and give it 512 MB of RAM. The template also asks for `IOSv_startup_config.img`, which GNS3 provides.
4. Add a **Cloud** node bound to the host-only adapter, plus an Ethernet switch, and wire them as above.
5. Apply `configs/ios-lab-N.cfg`. Save the project as `lab/netmgr.gns3` and commit it.

Option A deviates from SRS 8.1 (which names GNS3, with Containerlab as the fallback). If you
choose it, record the change as `docs/decisions/0004-cml-as-lab-platform.md`.

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
(ADR-0003), and that `.env.lab` has no placeholders left. It never prints `.env.lab` values. Then it
starts the API here and the live web UI in a second window. Options: `-CheckOnly` (run the checks,
start nothing), `-NoWeb` (API only, e.g. while Node is too old), `-Reinstall`.
`-ExecutionPolicy Bypass` is needed because Windows blocks `.ps1` scripts by default.

**4. Register the routers** on the Devices screen: names `ios-lab-1`…`ios-lab-4` (exactly the keys
in `.env.lab`), IPs `192.168.198.11`…`.14`.

**5. Smoke-test**, in a second terminal while the app runs:
```powershell
powershell -ExecutionPolicy Bypass -File scripts\check-lab.ps1
```
It prints a pass/fail table: API health, a syslog round trip (sent to 127.0.0.1), the firewall
rules, ping and TCP 22 to each router, and the app's own up/down state for each registered router.
"PASS" means *as expected*, so ios-lab-4 passes when it is unreachable. The local syslog test cannot
prove the routers' syslog gets through, which is why the firewall rows exist; still do the manual
syslog row in the table below.

Notes: the database is `network_manager.db` in the repo root (SQLite, git-ignored). The script
always starts from the repo root, so it is never created anywhere else. Delete the file to start fresh.

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

- **No syslog arriving:** allow inbound UDP/TCP 514 in Windows Defender Firewall (step 2 above).
- **Every router unreachable, even from `ping.exe`:** the lab isn't running or reachable. Check
  that CML and the routers are started and that WSL/Hyper-V is off (a
  `vEthernet (WSL ...)` adapter appearing is a sign it's on).
- **Windows can ping a router but the app shows it down:** `check-lab.ps1` flags this. Natively,
  check the API window for errors; in Docker, unprivileged ICMP may be blocked in the container
  (`docker compose logs api`).
- **SSH "no matching key exchange method":** IOSv offers only SHA-1 algorithms. For your own ssh client, add `-o KexAlgorithms=+diffie-hellman-group14-sha1 -o HostKeyAlgorithms=+ssh-rsa`. The app needs paramiko < 5 (pinned in `pyproject.toml`, ADR-0003).
