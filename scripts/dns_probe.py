"""Query a DNS server and print the result as JSON (used by scripts/check-lab.ps1).

Resolve-DnsName does not expose the AA (authoritative) flag, so the lab smoke test uses this
probe to check it (DNS plan, checkpoint A). Timing covers only the network round trip of each
query, not Python start-up, so it is comparable with NFR-3 (< 50 ms).

    python scripts/dns_probe.py r1.lab.local --type A --server 127.0.0.1 --port 53 --repeat 5
"""

import argparse
import json
import statistics
import sys
import time

from dnslib import QTYPE, RCODE, DNSRecord


def probe(name: str, qtype: str, server: str, port: int, timeout: float, repeat: int) -> dict:
    timings_ms: list[float] = []
    reply: DNSRecord | None = None
    for _ in range(repeat):
        query = DNSRecord.question(name, qtype)
        start = time.perf_counter()
        raw = query.send(server, port, tcp=False, timeout=timeout)
        timings_ms.append((time.perf_counter() - start) * 1000)
        reply = DNSRecord.parse(raw)
    assert reply is not None
    return {
        "ok": True,
        "rcode": RCODE.get(reply.header.rcode, str(reply.header.rcode)),
        "aa": bool(reply.header.aa),
        "answers": [
            {
                "name": str(rr.rname).rstrip("."),
                "type": QTYPE.get(rr.rtype, str(rr.rtype)),
                "value": str(rr.rdata).rstrip("."),
            }
            for rr in reply.rr
        ],
        "median_ms": round(statistics.median(timings_ms), 2),
        "max_ms": round(max(timings_ms), 2),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("name")
    parser.add_argument("--type", default="A")
    parser.add_argument("--server", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=53)
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--repeat", type=int, default=1)
    args = parser.parse_args(argv)
    try:
        result = probe(
            args.name, args.type, args.server, args.port, args.timeout, max(1, args.repeat)
        )
    except (OSError, TimeoutError) as exc:
        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
