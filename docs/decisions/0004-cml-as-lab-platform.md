# ADR-0004: Cisco Modeling Labs (CML) as the lab platform instead of GNS3

- **Status:** Accepted (2026-11-19)
- **Requirements:** SRS 8.1 (lab platform), 8.2 (simulated inventory), 8.4 (reproducibility), 6.2

## Context
SRS 8.1 names GNS3 as the lab platform, with Containerlab as the fallback. Either option needs
licensed Cisco images (IOSv) for the routers, because the configuration features target Cisco
IOS. One team member holds a CML subscription, which already includes IOSv and IOSvL2, licensed
for non-commercial testing. No other member has legitimate access to those images, so moving to
GNS3 would add installation work without letting anyone else run the lab.

## Decision
Run the lab in CML on the subscribing member's machine (VMware, NAT network 192.168.198.0/24).
The routers reach the app through a CML External Connector in System Bridge mode. The other members
develop against the faked device layer (SRS 8.3) and join lab sessions for integration and
acceptance testing.

## Consequences
- Fewer setup steps (no image extraction, no GNS3 VM), and the images stay within the license.
- Only one member can host the lab. Lab sessions are scheduled with that member, as the weekly
  integration session in SRS 10.2 already assumes.
- CML needs VMware nested virtualization, which conflicts with WSL2/Hyper-V, so the app runs
  natively on Windows during lab sessions (`scripts/run-lab.ps1`). Docker Compose remains the
  packaging for Linux hosts (SRS 5.3.4).
- CML Personal's 20-node limit covers the full SRS 8.2 inventory (12 nodes).
- Reproducibility (SRS 8.4): router configs and setup steps live in `lab/`. The CML topology is
  exported as YAML (image names only, no images).
