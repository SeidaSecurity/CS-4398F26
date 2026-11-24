"""Isolated, controlled, synthetic performance demonstration. No real CPU or network load testing.

The simulator listens only on loopback, consumes work requests in memory,
reads the standby router's saved interface config, and emits monitor-shaped JSON.
"""
from __future__ import annotations

import argparse
import os
import urllib.request
import subprocess
import sys
import json
import socket
import threading
import time
import math
from collections import deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PAGE = '''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>CS4398 — Scenario Controller</title><style>
body{margin:0;background:#101725;color:#f4f7fb;font:16px system-ui, sans-serif}.wrap{max-width:940px;margin:45px auto;padding:0 20px}h1{font-size:32px}h2{font-size:19px}.hint{color:#b4c1d3}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(205px,1fr));gap:14px}.panel{padding:20px;background:#1b2536;border:1px solid #344258;border-radius:14px}.number{font-size:32px;font-weight:700;margin:8px 0}button{border:0;background:#ee6547;color:white;font-weight:700;font-size:17px;padding:15px 22px;border-radius:10px;cursor:pointer;margin:6px 6px 6px 0}button.secondary{background:#324b6d}button:disabled{opacity:.45}code,pre{font-size:15px;background:#0a111d;border-radius:8px;padding:8px;white-space:pre-wrap}.green{color:#82dfab}.orange{color:#ffb077}.pill{display:inline-block;border-radius:99px;padding:7px 10px;background:#30405a}small{color:#b4c1d3}</style></head><body><main class="wrap"><p class="hint">CS4398 / Operations Console / Scenario Control</p><h1>Traffic Control & Capacity Response</h1><p class="hint">Generates bounded requests to a localhost-only simulated service. Synthetic CPU, memory and throughput are exposed through a read-only API bridge to the real capstone dashboard. No real resource exhaustion.</p><div class="panel"><h2>Presenter controls</h2><button onclick="go('/control/start')">▶ Generate Request Spike</button><button class="secondary" onclick="go('/control/stop')">■ Stop Requests</button><button class="secondary" onclick="go('/control/reset')">↺ Reset Scenario</button><p>Recovery is <b>not</b> activated here: your teammate must push <code>interface GigabitEthernet0/1\nno shutdown</code> to <b>Standby-R4</b> using the capstone Configuration → Push page.</p></div><div class="grid" style="margin-top:18px"><div class="panel"><h2>Request generator</h2><div id="state" class="number">—</div></div><div class="panel"><h2>Standby server</h2><div id="standby" class="number">—</div></div><div class="panel"><h2>Primary CPU (modeled)</h2><div id="cpu" class="number">—</div></div><div class="panel"><h2>Generated requests</h2><div id="count" class="number">—</div></div></div><p class="hint" id="note"></p><p><a style="color:#9cc9ff" href="http://127.0.0.1:5173" target="_blank">Open capstone monitoring dashboard</a></p><small>The Standby-R4 SSH management port is 2252. All services are loopback-only. Results are demonstration telemetry, not measured device load.</small></main><script>
async function go(p){const r=await fetch(p,{method:'POST'});if(!r.ok)alert(await r.text());refresh()};async function refresh(){try{const d=await (await fetch('/state')).json();document.getElementById('state').textContent=d.running?'ON':'OFF';document.getElementById('standby').textContent=d.standby_enabled?'ENABLED':'OFFLINE';document.getElementById('standby').className='number '+(d.standby_enabled?'green':'orange');document.getElementById('cpu').textContent=d.primary_cpu.toFixed(1)+'%';document.getElementById('count').textContent=d.request_count.toLocaleString();document.getElementById('note').textContent=d.message+(d.activation_registered?' • Standby-R4 marked UP in Inventory + topology.':d.activation_error?' • Inventory registration pending: '+d.activation_error:'')}catch(e){document.getElementById('note').textContent='Service unavailable: '+e}}setInterval(refresh,1000);refresh();</script></body></html>'''


def point(t: float, value: float) -> dict:
    return {"t": datetime.fromtimestamp(t, timezone.utc).isoformat(), "value": round(float(value), 2)}


class Scenario:
    def __init__(self, standby_state: Path, step: float = 1.5) -> None:
        self.standby_state = standby_state
        self.step = step
        self.lock = threading.RLock()
        self.running = False
        self.request_count = 0
        self.recent = deque(maxlen=2500)
        self.history = deque(maxlen=1500)
        self.last_standby = False
        self.cpu = 18.0
        self.last_tick = 0.0
        self.last_syslog = 0.0
        self.last_syslog_standby = False
        self.last_batch = -1
        self.sent_in_batch = 0
        self.last_log_kind = ""
        self.worker_online = False
        self.worker_process = None
        self.activation_registered = False
        self.activation_error = ""
        self.event_counts = {"warnings": 0, "errors": 0, "information": 0}
        self.history.append((time.time(), 18.0, 22.0, 18000.0, 12000.0, False, False))

    def standby(self) -> bool:
        try:
            cfg = json.loads(self.standby_state.read_text(encoding='utf8'))
            return not cfg['interfaces']['GigabitEthernet0/1']['shutdown']
        except (OSError, ValueError, KeyError, TypeError):
            return False

    def reset(self) -> None:
        with self.lock:
            self.running = False
            self.recent.clear()
            self.request_count = 0
            self.cpu = 18.0
            self.event_counts = {"warnings": 0, "errors": 0, "information": 0}
            self.history.clear()
            self.history.append((time.time(), 18.0, 22.0, 18000.0, 12000.0, False, False))
            # Do not silently rewrite standby config; reset is handled in the launcher or via SSH push.

    def work(self) -> None:
        with self.lock:
            self.request_count += 1
            self.recent.append(time.time())

    def tick(self, now: float | None = None) -> None:
        now = now or time.time()
        with self.lock:
            if now - self.last_tick < self.step:
                return
            self.last_tick = now
            while self.recent and self.recent[0] < now - 4:
                self.recent.popleft()
            rate = len(self.recent) / 4.0
            standby = self.standby()
            # Three workers handle the initial traffic; the fourth joins after push.
            # Model network-wide CPU rising visibly under overload, then falling on recovery.
            # Enabling standby halves modeled primary load, with a smooth downward curve.
            target = min(97.0, 18.0 + 3.0 * rate) if not standby else min(46.0, 18.0 + 0.45 * rate)
            self.cpu += (target - self.cpu) * 0.42
            memory = 22.0 + self.cpu * 0.62
            # Visible, bounded traffic oscillations only after 500 generated requests.
            # This is modeled telemetry, not physical CPU exhaustion.
            if self.running and self.request_count >= 500 and not standby:
                self.cpu = max(65.0, min(97.0, self.cpu + 6.0 * math.sin(now * 1.35)))
            # Model traffic capacity per device: after failover, primary ingress drops.
            # Total offered request rate stays the same; individual device load falls.
            pulse = 1.0 + (0.25 * math.sin(now * 1.35) if self.running and self.request_count >= 500 and not standby else 0.0)
            incoming = (18000.0 + rate * (7500.0 if standby else 33000.0)) * pulse
            outgoing = (12000.0 + rate * (5500.0 if standby else 24000.0)) * pulse
            self.history.append((now, self.cpu, memory, incoming, outgoing, standby, self.running))
            self.last_standby = standby

    def state(self) -> dict:
        self.tick()
        with self.lock:
            standby = self.standby()
            message = 'Load redistributed after capstone SSH push' if standby and self.running else ('Waiting for Configuration → Push to enable standby' if self.running else 'Press Generate Request Spike to begin')
            overloaded = self.running and not standby and self.cpu >= 70
            warnings = [
                {"severity": "critical" if self.cpu >= 90 else "warning",
                 "source": "Primary-R1", "message": f"High CPU utilization on primary: {self.cpu:.1f}%"},
                {"severity": "warning", "source": "Primary-R1",
                 "message": "Request queue pressure detected. Standby-R4 is disabled."},
            ] if overloaded else []
            return {"running": self.running, "standby_enabled": standby,
                    "request_count": self.request_count, "primary_cpu": round(self.cpu, 2),
                    "active_warnings": warnings, "active_warning_count": len(warnings),
                    "event_counts": dict(self.event_counts), "request_rate_threshold": 500,
                    "insight": incident_insight(self.running, standby, self.cpu, self.request_count), "worker_online": self.worker_online, "activation_registered": self.activation_registered, "activation_error": self.activation_error, "message": message,
                    "telemetry_source": "synthetic localhost scenario"}

    def metrics(self, window: str = '1h', device: bool = False, device_name: str = "") -> dict:
        self.tick()
        length = {'1h': 3600, '24h': 86400, '7d': 604800}.get(window, 3600)
        with self.lock:
            rows = [r for r in self.history if r[0] >= time.time() - length]
        # Four independent device series; standby is disabled before activation.
        # Three workers share the synthetic pre-spike pool, and the fourth takes traffic after the push.
        if device:
            standby_device = device_name == "Standby-R4"
            def cpu_for(r):
                return (0 if not r[5] else 16 + min(30, max(0, r[1] - 18))) if standby_device else r[1]
            def mem_for(r):
                return 0 if standby_device and not r[5] else 22 + cpu_for(r) * .62
            def traffic_for(r, n):
                return 0 if standby_device and not r[5] else r[n] * (.33 if standby_device and r[5] else 1.0)
            return {"cpu": [point(r[0], cpu_for(r)) for r in rows],
                    "memory": [point(r[0], mem_for(r)) for r in rows],
                    "throughput_in_bps": [point(r[0], traffic_for(r, 3)) for r in rows],
                    "throughput_out_bps": [point(r[0], traffic_for(r, 4)) for r in rows]}
        return {"devices_up": [point(r[0], 4 if r[5] else 3) for r in rows],
                "cpu_avg": [point(r[0], r[1]) for r in rows],
                "throughput_in_bps": [point(r[0], r[3]) for r in rows],
                "throughput_out_bps": [point(r[0], r[4]) for r in rows]}


def incident_insight(running: bool, standby: bool, cpu: float, requests: int) -> dict:
    """Explainable rule-based triage, not a trained AI model."""
    if running and not standby and cpu >= 70:
        return {'level':'critical' if cpu >= 88 else 'warning',
                'title':'Capacity bottleneck detected',
                'evidence':f'Primary CPU {cpu:.0f}% • {requests:,} requests • standby unavailable',
                'recommendation':'Enable Standby-R4 via Configuration Push to redistribute modeled request load.',
                'method':'Rule-based incident analysis · simulated telemetry'}
    if running and standby:
        return {'level':'healthy','title':'Load redistribution confirmed',
                'evidence':f'Four devices available • primary CPU {cpu:.0f}%',
                'recommendation':'Observe recovery trend and review retained incident logs.',
                'method':'Rule-based incident analysis · simulated telemetry'}
    return {'level':'normal','title':'Capacity operating within baseline',
            'evidence':f'Three devices online • primary CPU {cpu:.0f}%',
            'recommendation':'Run workload to observe capacity and incident response.',
            'method':'Rule-based incident analysis · simulated telemetry'}

def build_syslog(scenario: Scenario, severity: int, now: float, sequence: int) -> bytes:
    """RFC5424 syslog generated by the local workload simulator.

    Every record identifies its synthetic origin in its message body.
    """
    level = 'ERROR' if severity == 3 else 'WARNING' if severity == 4 else 'INFO'
    standby = scenario.standby()
    status = 'standby enabled, request pressure normalized' if standby else 'request backlog above capacity'
    body = (f'[DEMO: SIMULATED] {level} sequence={sequence} '
            f'cpu={scenario.cpu:.1f}% requests={scenario.request_count} {status}')
    priority = 16 * 8 + severity
    stamp = datetime.fromtimestamp(now, timezone.utc).isoformat().replace('+00:00', 'Z')
    return f'<{priority}>1 {stamp} Primary-R1 cs4398-scenario - - - {body}'.encode()


def send_log_batch(scenario: Scenario, transport, now: float | None = None) -> int:
    """Up to 210 warnings/errors per four-second epoch during overload.

    The batch is deliberately sent in uneven waves (150 then 60), so the
    actual event-rate graph fluctuates; no events are fabricated by the UI.
    The total is bounded to 210/4s and terminates when standby is enabled.
    """
    now = time.time() if now is None else now
    with scenario.lock:
        if not scenario.running or scenario.standby():
            return 0
        epoch = int(now // 4)
        if scenario.last_batch != epoch:
            scenario.last_batch = epoch
            scenario.sent_in_batch = 0
        phase = now - epoch * 4
        quota = 150 if phase < 1.8 else 210
        count = max(0, quota - scenario.sent_in_batch)
        messages = []
        for offset in range(count):
            index = scenario.sent_in_batch + offset
            severity = 3 if index % 5 < 2 else 4
            messages.append((severity,build_syslog(scenario,severity,now,scenario.event_counts['warnings']+scenario.event_counts['errors']+offset+1)))
        for severity, message in messages:
            transport(message)
            scenario.event_counts['errors' if severity == 3 else 'warnings'] += 1
        scenario.sent_in_batch += count
        return count


def event_reporter(scenario: Scenario, port: int = 1515) -> None:
    """Sequential TCP syslog stream avoids per-message UDP thread/SQLite contention."""
    last_recovery = 0.0
    while True:
        try:
            with socket.create_connection(('127.0.0.1', port),timeout=2) as conn:
                while True:
                    scenario.tick()
                    now=time.time()
                    if scenario.running and not scenario.standby():
                        # Stream packets as distinct newline-delimited RFC5424 records.
                        send_log_batch(scenario,lambda line: conn.sendall(line+b'\n'),now)
                    elif scenario.running and scenario.standby() and now-last_recovery >= 10:
                        with scenario.lock:
                            message = build_syslog(scenario,6,now,scenario.event_counts['information']+1)
                            conn.sendall(message+b'\n')
                            scenario.event_counts['information'] += 1
                        last_recovery=now
                    time.sleep(.15)
        except (OSError,ConnectionError):
            # Collector may not yet be listening during startup; retry without busy-looping.
            time.sleep(1.0)

def make_handler(scenario: Scenario):
    class Handler(BaseHTTPRequestHandler):
        def send(self, content: bytes, status: int = 200, content_type: str = 'application/json'):
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(content)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(content)

        def do_GET(self):
            path = urlparse(self.path)
            if path.path == '/':
                return self.send(PAGE.encode(), content_type='text/html; charset=utf-8')
            if path.path == '/health':
                return self.send(b'{"ok":true,"source":"synthetic demonstration"}')
            if path.path == '/state':
                return self.send(json.dumps(scenario.state()).encode())
            if path.path in ('/metrics/network', '/metrics/device'):
                args = parse_qs(path.query)
                window = args.get('window', ['1h'])[0]
                data = scenario.metrics(window, device=path.path.endswith('/device'), device_name=args.get('name', [''])[0])
                return self.send(json.dumps(data).encode())
            return self.send(b'{"error":"not found"}', 404)

        def do_POST(self):
            path = urlparse(self.path).path
            if path == '/control/start':
                with scenario.lock:
                    scenario.running = True
            elif path == '/control/stop':
                with scenario.lock:
                    scenario.running = False
            elif path == '/control/reset':
                scenario.reset()
            elif path == '/work':
                scenario.work()
            else:
                return self.send(b'{"error":"not found"}', 404)
            return self.send(b'{"ok":true}')

        def log_message(self, *_args):
            return
    return Handler


def generator(scenario: Scenario) -> None:
    # Bounded local workload: 24 HTTP posts/sec at most, loopback only.
    import urllib.request
    interval = 1.0 / 24.0
    while True:
        with scenario.lock:
            running = scenario.running
        if running:
            try:
                urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8765/work', data=b'', method='POST'), timeout=0.5).close()
            except OSError:
                pass
            time.sleep(interval)
        else:
            time.sleep(0.15)


def activate_inventory_standby(scenario: Scenario) -> bool:
    """Reflect the existing fourth device's SSH-configured enabled state in Inventory."""
    if not scenario.standby():
        return False
    token = os.getenv('CS4398_SCENARIO_ACTIVATION_TOKEN', '')
    if not token:
        scenario.activation_error = 'Missing activation token'
        return False
    req = urllib.request.Request(
        'http://127.0.0.1:8000/api/v1/demo/activate-standby',
        data=b'{}', headers={'X-Demo-Token': token, 'Content-Type': 'application/json'},
        method='POST')
    try:
        with urllib.request.urlopen(req, timeout=2) as result:
            data = json.load(result)
        scenario.activation_registered = bool(data.get('ok'))
        scenario.activation_error = ''
        return scenario.activation_registered
    except Exception as exc:
        scenario.activation_error = str(exc)
        return False


def inventory_watcher(scenario: Scenario, _worker_state_dir: Path) -> None:
    while True:
        if scenario.standby() and not scenario.activation_registered:
            activate_inventory_standby(scenario)
        time.sleep(.5)


def ticker(scenario: Scenario) -> None:
    while True:
        scenario.tick()
        time.sleep(0.3)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--standby-state', type=Path, required=True)
    parser.add_argument('--syslog-port', type=int, default=1515)
    parser.add_argument('--worker-state-dir', type=Path, required=True)
    args = parser.parse_args()
    scenario = Scenario(args.standby_state)
    threading.Thread(target=generator, args=(scenario,), daemon=True).start()
    threading.Thread(target=ticker, args=(scenario,), daemon=True).start()
    threading.Thread(target=event_reporter, args=(scenario, args.syslog_port), daemon=True).start()
    threading.Thread(target=inventory_watcher, args=(scenario, args.worker_state_dir), daemon=True).start()
    server = ThreadingHTTPServer(('127.0.0.1', 8765), make_handler(scenario))
    print('CONTROL READY: http://127.0.0.1:8765', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
