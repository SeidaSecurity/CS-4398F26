"""Opt-in capstone API adapter for isolated presentation telemetry.

Read-only HTTP API-to-API bridge; never writes synthetic samples to the SQL database.
Turn on by setting CS4398_DEMO_METRICS_URL=http://127.0.0.1:8765.
"""
from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen


def fetch_demo_metrics(kind: str, window: str, device_name: str = "") -> dict | None:
    base = os.getenv('CS4398_DEMO_METRICS_URL', '').rstrip('/')
    if not base:
        return None
    # Restrict to a localhost-only source. The demo never needs network exposure.
    if base not in ('http://127.0.0.1:8765', 'http://localhost:8765'):
        return None
    if kind not in ('network', 'device') or window not in ('1h', '24h', '7d'):
        return None
    try:
        with urlopen(f'{base}/metrics/{kind}?{urlencode({"window": window, "name": device_name})}', timeout=0.5) as result:
            return json.load(result)
    except (OSError, ValueError, URLError, HTTPError):
        return None


def fetch_demo_state() -> dict | None:
    """Get opt-in scenario alert state from the localhost simulator only."""
    base = os.getenv('CS4398_DEMO_METRICS_URL', '').rstrip('/')
    if base not in ('http://127.0.0.1:8765', 'http://localhost:8765'):
        return None
    try:
        with urlopen(f'{base}/state', timeout=0.5) as result:
            return json.load(result)
    except (OSError, ValueError, URLError, HTTPError):
        return None
