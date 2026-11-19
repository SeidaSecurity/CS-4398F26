# Virtual Lab (SRS Appendix II)

Rebuilds the test network from a clean checkout. Device images come from each member's own Cisco
Modeling Labs (CML) subscription, used for non-commercial testing only. **Images are never
committed** (`.gitignore` blocks `*.qcow2`, `*.iso`, and `lab/images/`).

## Topology (Tracks A and B)

```
   Windows host 192.168.56.1  (app: API :8000, syslog :514)
              |
     [External connector / Cloud]  -- host-only network 192.168.56.0/24
              |
         [L2 switch]
      /     |      |      \
 ios-lab-1 ios-lab-2 ios-lab-3 ios-lab-4
   .11       .12       .13      .14 (powered off: "unreachable node", AT-03)
```

Track C will add hosts and switches for DHCP/DNS later (SRS 8.2).

## Option A: run the lab in CML (fewest steps)

1. In CML: add 4 × **IOSv** nodes, 1 × **unmanaged switch**, and 1 × **External Connector**.
   Set the connector to **System Bridge** (`bridge0`), so the routers share an L2 segment with the
   network the CML VM's NIC is on.
2. Put the CML VM's network adapter on the **host-only** network 192.168.56.0/24 (VMware: VMnet1,
   or a custom host-only net). Windows is then `192.168.56.1` on that adapter.
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
choose it, record the change as `docs/decisions/0003-cml-as-lab-platform.md`.

## Point the app at the lab

Local `.env` (git-ignored; values must match what you put in the router configs):

```
MONITORING_ENABLED=true
SNMP_COMMUNITY=<same as SNMP_COMMUNITY in the configs>
SYSLOG_ENABLED=true
NETMGR_DEVICE_CREDENTIALS_JSON={"ios-lab-1":{"username":"lab","password":"<LAB_PASSWORD>"},"ios-lab-2":{"username":"lab","password":"<LAB_PASSWORD>"},"ios-lab-3":{"username":"lab","password":"<LAB_PASSWORD>"},"ios-lab-4":{"username":"lab","password":"<LAB_PASSWORD>"}}
```

Start with `docker compose up --build`, then `cd web && VITE_API_MODE=live npm run dev`
(requires Node ≥ 22.12). Add each device in the UI using **exactly** the name from the credentials JSON.

## Smoke test (run before any acceptance test)

| Check | Command / action | Expected |
|---|---|---|
| L3 reachability | `ping 192.168.56.11` from Windows | Replies |
| SSH | `ssh lab@192.168.56.11` | Router prompt |
| SNMP (optional, from WSL) | `snmpwalk -v2c -c <community> 192.168.56.11 1.3.6.1.2.1.2.2.1.2` | Interface names |
| Polling | Open the dashboard and wait 60 s | ios-lab-1..3 **up**; ios-lab-4 **down** after 2 polls |
| Syslog | On a router: `conf t` → `int lo0` → `shut` → `no shut` | Message appears on the Logs page |
| Config retrieve | History → retrieve | A version is saved |

## Troubleshooting

- **No syslog arriving:** allow inbound UDP/TCP 514 in Windows Defender Firewall.
- **Every device down, but SSH works:** unprivileged ICMP may be blocked inside the container.
  Check `docker compose logs api`.
- **SSH fails with a key-exchange error:** older IOSv offers legacy algorithms. Make sure Netmiko
  is current; if needed, regenerate keys with `crypto key generate rsa modulus 2048`.
