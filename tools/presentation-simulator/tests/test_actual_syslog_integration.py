"""Exercise actual project's RFC5424 receiver + SQLite, not only mock socket."""
import os
import subprocess
import sys
import unittest

class SyslogIntegration(unittest.TestCase):
    def test_simulated_syslog_persists_and_classifies_in_real_backend(self):
        repo = os.getenv('CS4398_INSTALLED_TEST_REPO')
        if not repo:
            self.skipTest('set CS4398_INSTALLED_TEST_REPO')
        script = r'''
import os,socket,time,tempfile
from sqlalchemy import select
from pathlib import Path
from app.database import engine, SessionLocal, Base
from app.models import LogRecord
from app.syslog import SyslogReceivers
Base.metadata.create_all(engine)
receiver=SyslogReceivers('127.0.0.1',0,0)
port=receiver.servers[0].server_address[1]
receiver.start()
try:
 from datetime import datetime,timezone
 now=datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
 payload=f'<131>1 {now} Primary-R1 cs4398-demo - - - DEMO SIMULATED CRITICAL primary CPU 96% - request overload'
 sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
 sock.sendto(payload.encode(),('127.0.0.1',port));sock.close()
 for i in range(40):
  with SessionLocal() as session:
   row=session.scalar(select(LogRecord).where(LogRecord.source=='Primary-R1'))
   if row:
    assert row.parsed and row.severity==3,row
    assert 'DEMO SIMULATED CRITICAL' in row.body
    break
  time.sleep(.05)
 else:raise AssertionError('real UDP syslog not stored')
finally:receiver.stop()
print('PASS real UDP syslog stored, parsed and severity=3')
'''
        with __import__('tempfile').TemporaryDirectory() as directory:
            env = {**os.environ, 'DATABASE_URL':f'sqlite:///{directory}/log-test.db'}
            cp = subprocess.run([sys.executable,'-c',script],cwd=repo,env=env,text=True,capture_output=True,timeout=15)
        self.assertEqual(cp.returncode,0,cp.stdout+cp.stderr)
