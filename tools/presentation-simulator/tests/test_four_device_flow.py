"""Four-device control-plane and telemetry checks; no real SSH/SNMP dependencies."""
import json
import tempfile
import time
from pathlib import Path
from unittest.mock import Mock
from simulator import Scenario, build_syslog
from virtual_router import RouterCLI, RouterState


def test_real_cli_push_changes_state_and_recovers_all_metrics():
    with tempfile.TemporaryDirectory() as directory:
        path=Path(directory)/'router.json'
        state=RouterState(path,'Standby-R4')
        state.data['interfaces']['GigabitEthernet0/1']['shutdown']=True
        state.save()
        demo=Scenario(path,step=0)
        demo.running=True
        now=time.time()
        for n in range(12):
            t=now+n*1.5
            demo.recent.extend(t-i/24 for i in range(96))
            demo.tick(t)
        peak=demo.cpu
        before=demo.metrics('1h')['throughput_in_bps'][-1]['value']
        assert peak>=80
        assert demo.metrics('1h')['devices_up'][-1]['value']==3
        assert demo.state()['active_warning_count']>0
        cli=RouterCLI(state)
        cli.execute('enable')
        cli.execute('configure terminal')
        cli.execute('interface GigabitEthernet0/1')
        cli.execute('no shutdown')
        assert state.data['interfaces']['GigabitEthernet0/1']['shutdown'] is False
        assert json.loads(path.read_text())['interfaces']['GigabitEthernet0/1']['shutdown'] is False
        for n in range(12,24):
            t=now+n*1.5
            demo.recent.extend(t-i/24 for i in range(96))
            demo.tick(t)
        assert demo.cpu < peak - 25
        assert demo.metrics('1h')['throughput_in_bps'][-1]['value'] < before / 2
        assert demo.metrics('1h')['devices_up'][-1]['value']==4
        assert demo.state()['active_warning_count']==0
        assert demo.metrics('1h',device=True,device_name='Standby-R4')['cpu'][-1]['value']>0


def test_warning_error_and_recovery_syslog_are_parsable():
    from datetime import datetime, timezone
    with tempfile.TemporaryDirectory() as directory:
        cfg=Path(directory)/'router.json'
        cfg.write_text(json.dumps({'interfaces':{'GigabitEthernet0/1':{'shutdown':True}}}))
        demo=Scenario(cfg,step=999)
        demo.running=True
        demo.cpu=90
        now=time.time()
        for severity, expected in ((4,b'<132>1 '),(3,b'<131>1 '),(6,b'<134>1 ')):
            packet=build_syslog(demo,severity,now,1)
            assert packet.startswith(expected)
            assert b'[DEMO: SIMULATED]' in packet
