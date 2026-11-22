r"""Lab check for R2.3: print CPU, memory and interface counts each router reports over SNMP.

Usage: .venv\Scripts\python scripts\check_snmp.py 192.168.198.11 192.168.198.12 ...
Reads SNMP_COMMUNITY from .env.lab (or the environment) and never prints it.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models import Device  # noqa: E402
from app.probes import snmp_probe  # noqa: E402


def community() -> str:
    value = os.getenv("SNMP_COMMUNITY")
    env_file = Path(__file__).resolve().parents[1] / ".env.lab"
    if not value and env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("SNMP_COMMUNITY="):
                value = line.split("=", 1)[1].strip()
    if not value:
        sys.exit("SNMP_COMMUNITY is not set in the environment or .env.lab.")
    return value


def main(addresses: list[str]) -> int:
    secret, failures = community(), 0
    print(f"{'address':<16} {'result':<6} {'cpu %':>6} {'mem %':>6} {'ifaces':>6}")
    for number, address in enumerate(addresses, start=1):
        try:
            result = snmp_probe(Device(id=number, name=address, management_ip=address), secret)
        except Exception as exc:  # report the kind of failure only; never echo the community
            failures += 1
            print(f"{address:<16} {'FAIL':<6} {type(exc).__name__}")
            continue
        cpu = "-" if result.cpu_pct is None else f"{result.cpu_pct:.1f}"
        mem = "-" if result.memory_pct is None else f"{result.memory_pct:.1f}"
        ok = result.cpu_pct is not None and result.memory_pct is not None
        failures += not ok
        print(f"{address:<16} {'PASS' if ok else 'FAIL':<6} {cpu:>6} {mem:>6} "
              f"{len(result.interfaces or []):>6}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["192.168.198.11", "192.168.198.12", "192.168.198.13"]))
