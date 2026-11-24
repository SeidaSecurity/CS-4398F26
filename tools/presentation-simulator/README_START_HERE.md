# CS4398 Presentation Rebuild v6 — frontend repair

**This release fixes the v5 Network page white screen caused by reading `devicesQuery.data` before its declaration.** It also introduces a fail-fast production build before launching Vite, so React/TypeScript errors stop the launcher instead of leaving a blank browser page.

## Installation

1. Stop your old launcher with Control+C and unzip this folder to `~/Downloads/CS4398_Presentation_Rebuild_v6`.
2. On your capstone feature branch, ensure your working tree has no unrelated changes: `cd ~/Documents/capstone && git status`.
3. Run `bash ~/Downloads/CS4398_Presentation_Rebuild_v6/Install_API_Bridge.command`.
4. Run `bash ~/Downloads/CS4398_Presentation_Rebuild_v6/Start_Presentation_Demo.command`.
5. The launcher now runs `npm run build` and does not announce `APP READY` unless compilation and server startup succeed.

**If already on v5:** Running the new installer repairs the existing page without resetting your presentation database. You can also run `python3 ~/Downloads/CS4398_Presentation_Rebuild_v6/repair_network_screen.py --repo ~/Documents/capstone` and then `cd ~/Documents/capstone/web && npm run build`.

## Presentation checklist

- Open Inventory: Primary-R1, Worker-R2, Worker-R3 are Up; Standby-R4 is Down.
- Open Network, select All devices. The independent controller is at http://127.0.0.1:8765.
- Press Generate Request Spike and observe the modeled CPU/throughput, network activity, log severity and active capacity alerts.
- In Configuration → Push, select **Standby-R4 only** and push `interface GigabitEthernet0/1` followed by `no shutdown`.
- Inventory should change to 4 Up; the modeled primary load should fall. Historical logs remain until they age out of the two-minute window.
- Run `bash ~/Downloads/CS4398_Presentation_Rebuild_v6/Verify_Demo.command` to inspect real stored event counts; simulated measurements are not physical router counters.

**Scope of verification:** No system can be guaranteed to work on your Mac without a full local run. The included automated tests exercise the scenario and APIs; the frontend build is required and executed by the updated launcher on your Mac.

---

# CS 4398 — Incident Response Presentation (v6 — repaired)

This is a **local, controlled performance scenario** for the team's existing capstone app. The routers expose IOS-like SSH CLIs, not Cisco IOS, and the CPU / memory / throughput series are modeled. **All generated syslog messages explicitly contain `[DEMO: SIMULATED]`.** The syslog messages are delivered to and stored by the real capstone collector. A new read-only API aggregates those stored messages for the Network tab.

## What the class will see

1. **At launch:** four devices already appear in Inventory and the topology: Primary-R1 / Worker-R2 / Worker-R3 = **Up**, Standby-R4 = **Down**.
2. In a separate controller at `http://127.0.0.1:8765`, click **Generate Request Spike**. CPU, throughput and memory rise. After 500 requests the modeled throughput begins fluctuating, and the syslog generator transmits **210 warning/error records every full four-second epoch** as two uneven bursts, rather than a flat 4-per-second trickle.
3. The existing capstone **Network** tab reads events from its stored syslog table through `/api/v1/monitoring/incident-activity`. **Network activity** and **Log severity** show last-two-minute 2.5-second-bucket fluctuations. The right panel shows capacity alerts and **Incident Intelligence** (an explainable rule-based summary, not a trained AI model).
4. Teammate opens capstone **Configuration → Push**, targets **Standby-R4 only**, enters:

   ```text
   interface GigabitEthernet0/1
   no shutdown
   ```

5. With a successful SSH push, the standby config changes on disk, the simulator detects the newly enabled interface, Inventory marks the fourth device **Up**, CPU and **per-primary** traffic decline, new severe event bursts stop, and the active alerts clear. Older warnings/errors remain in event history until the two-minute window rolls off. No recovery button is necessary.

## Install the upgrade

1. Stop the previous launcher using **Control+C**. Do not run two launchers simultaneously.
2. Unzip this ZIP into `~/Downloads/CS4398_Incident_Response_Presentation_v5` (keep the directory name unchanged).
3. Inside `~/Documents/capstone`, choose your existing **feature branch**; don't install directly on `main`. Run `git status` to ensure there are no unrelated uncommitted edits.
4. In Mac Terminal:

   ```bash
   bash ~/Downloads/CS4398_Incident_Response_Presentation_v5/Install_API_Bridge.command
   bash ~/Downloads/CS4398_Incident_Response_Presentation_v5/Start_Presentation_Demo.command
   ```

5. Log in at `http://127.0.0.1:5173`. Use the separate controller at `http://127.0.0.1:8765`.
6. Navigate to **Network → All devices**. Click the generator button and watch **Network activity**, **Log severity**, and the **Incident Intelligence** right panel. If you use a per-device filter, use **Primary-R1**, because that is the RFC5424 log source.
7. In **Configuration → Push**, target Standby-R4, paste the exact two commands above, and complete the push. Confirm the fourth Inventory device changes from Down to Up and the modeled overload resolves.

## Verification and troubleshooting

- Run: `bash ~/Downloads/CS4398_Incident_Response_Presentation_v5/Run_Automated_Tests.command` (uses your capstone `.venv` and checks integration with the actual application dependencies).
- Run: `bash ~/Downloads/CS4398_Incident_Response_Presentation_v5/Verify_Demo.command` (inspects devices, topology and recorded logs).
- Health check: `http://127.0.0.1:8765/health` and `http://127.0.0.1:8000/health`.
- Aggregated log API: `/api/v1/monitoring/incident-activity?seconds=120` (requires the application's normal login session).
- Controller state: `http://127.0.0.1:8765/state`.
- If the graph is blank: ensure the **updated** installer ran, ports TCP 1515 and 8000 are free, and that the backend has `SYSLOG_ENABLED=true`. Check the backend log printed by the launcher. At >50 logs/s a laptop may have trouble storing every record; measure what the verification script reports rather than claiming all generated messages were received.
- If the standby is already enabled, stop and restart the launcher: it resets only the standby interface (not your general inventory).
- Existing one-hour historical records retain past events. The live two-minute rolling charts decline after severe-event generation stops; historical event totals are not erased.
- **Do not claim Cisco SNMP or actual hardware utilization was measured.** This is an operational workflow presentation using a real app, a real SSH CLI connection, and explicitly modeled capacity signals.

## Testing performed in the authoring environment

- 10 scenario/HTTP tests passed; 2 project-dependency integration tests skipped because their dependencies were not installed in that environment.
- The v5 API/UI installer was applied twice to an existing v4 repository copy (upgrade/idempotence tested).
- The capstone's actual TCP syslog receiver stored all 210 generated records in a local SQLite test; aggregation returned 210 total, 84 errors and 126 warnings.
- The new Network page passed a TypeScript syntactic transpilation check, **not** a full Vite production build.
- The complete Mac React browser + Netmiko SSH push still requires a rehearsal on your computer.

To undo the changes, use Git on your feature branch. The installer also creates `*.bak` backups for the project API and Network page on first modification.
