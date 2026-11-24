"""Validate the bounded high-volume incident stream and explicit provenance."""
import json
import tempfile
import time
from pathlib import Path

from simulator import Scenario, build_syslog, incident_insight, send_log_batch


def scenario_in(folder):
    cfg = Path(folder) / 'router.json'
    cfg.write_text(json.dumps({'interfaces': {'GigabitEthernet0/1': {'shutdown': True}}}))
    scenario = Scenario(cfg, step=999)
    scenario.running = True
    scenario.cpu = 92
    scenario.last_tick = time.time()
    return scenario, cfg


def test_two_hundred_and_ten_per_four_seconds_and_provenance():
    with tempfile.TemporaryDirectory() as folder:
        s, cfg = scenario_in(folder)
        sent = []
        epoch = int(time.time() // 4) * 4
        assert send_log_batch(s, sent.append, epoch + 0.5) == 150
        assert send_log_batch(s, sent.append, epoch + 0.8) == 0
        assert send_log_batch(s, sent.append, epoch + 2.3) == 60
        assert send_log_batch(s, sent.append, epoch + 3.4) == 0
        assert len(sent) == 210
        assert all(b'[DEMO: SIMULATED]' in m for m in sent)
        assert all(m.startswith((b'<131>1 ', b'<132>1 ')) for m in sent)
        assert s.event_counts['warnings'] == 126
        assert s.event_counts['errors'] == 84
        cfg.write_text(json.dumps({'interfaces': {'GigabitEthernet0/1': {'shutdown': False}}}))
        assert send_log_batch(s, sent.append, epoch + 4.5) == 0
        assert len(sent) == 210


def test_fluctuates_after_500_requests():
    with tempfile.TemporaryDirectory() as folder:
        s, cfg = scenario_in(folder)
        s.step = 0
        s.request_count = 501
        now = time.time()
        rates = []
        for i in range(10):
            tick = now + i * 1.5
            s.recent.extend(tick - j / 24 for j in range(96))
            s.tick(tick)
            rates.append(s.metrics()['throughput_in_bps'][-1]['value'])
        assert max(rates) > min(rates) * 1.1
        assert incident_insight(True,False,91,520)['level'] == 'critical'
        cfg.write_text(json.dumps({'interfaces': {'GigabitEthernet0/1': {'shutdown': False}}}))
        assert incident_insight(True,True,40,550)['level'] == 'healthy'


def test_rfc5424_recovery_info():
    with tempfile.TemporaryDirectory() as folder:
        s, cfg = scenario_in(folder)
        cfg.write_text(json.dumps({'interfaces': {'GigabitEthernet0/1': {'shutdown': False}}}))
        record = build_syslog(s, 6, time.time(), 1)
        assert record.startswith(b'<134>1 ')
        assert b'DEMO: SIMULATED' in record
