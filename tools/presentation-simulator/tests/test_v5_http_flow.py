"""End-to-end local controller HTTP -> load -> SSH state -> recovery (no Netmiko)."""
import json
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen, Request

from simulator import Scenario, make_handler, send_log_batch


def request(url,post=False):
    with urlopen(Request(url,data=b'' if post else None,method='POST' if post else 'GET'),timeout=2) as response:
        return json.load(response)


def test_http_start_activity_and_automatic_recovery():
    with tempfile.TemporaryDirectory() as folder:
        cfg=Path(folder)/'router.json'
        cfg.write_text(json.dumps({'interfaces':{'GigabitEthernet0/1':{'shutdown':True}}}))
        scenario=Scenario(cfg,step=0)
        server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(scenario))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base=f'http://127.0.0.1:{server.server_port}'
        try:
            assert request(base+'/state')['standby_enabled'] is False
            request(base+'/control/start',True)
            for _ in range(520):scenario.work()
            now=time.time()
            for i in range(8):
                tick=now+i*1.5
                scenario.recent.extend(tick-j/24 for j in range(96))
                scenario.tick(tick)
            state=request(base+'/state')
            assert state['request_count']>=500 and state['primary_cpu']>70
            assert state['insight']['level'] in ('critical','warning')
            logs=[]
            epoch=int(time.time()//4)*4
            assert send_log_batch(scenario,logs.append,epoch+.5)==150
            assert send_log_batch(scenario,logs.append,epoch+2.5)==60
            assert len(logs)==210 and all(b'[DEMO: SIMULATED]' in item for item in logs)
            before=request(base+'/metrics/network')['cpu_avg'][-1]['value']
            # The configuration push saves this same state through the router SSH interface.
            cfg.write_text(json.dumps({'interfaces':{'GigabitEthernet0/1':{'shutdown':False}}}))
            for i in range(8,17):
                tick=now+i*1.5
                scenario.recent.extend(tick-j/24 for j in range(96))
                scenario.tick(tick)
            after=request(base+'/metrics/network')['cpu_avg'][-1]['value']
            assert after < before
            assert request(base+'/metrics/network')['devices_up'][-1]['value']==4
            assert request(base+'/state')['active_warning_count']==0
            assert send_log_batch(scenario,logs.append,epoch+4.5)==0
        finally:
            server.shutdown();server.server_close();thread.join(timeout=2)
