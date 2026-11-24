import os, subprocess,sys,unittest
class APIIntegration(unittest.TestCase):
 def test_four_device_inventory_activation(self):
  repo=os.getenv('CS4398_INSTALLED_TEST_REPO')
  if not repo:self.skipTest('set CS4398_INSTALLED_TEST_REPO to an installed repository')
  code=r"""
import sys,types,os
from fastapi import FastAPI,Depends
from fastapi.testclient import TestClient
from sqlalchemy import create_engine,select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app.database import Base,get_session
stubconf=types.ModuleType('app.configuration');stubconf.record_audit_event=lambda *args,**kwargs:None
sys.modules['app.configuration']=stubconf
from app.auth import enforce_access
from app.models import Device,DeviceState,TopologyLink
stub=types.ModuleType('app.credentials');stub.store_credentials=lambda *args,**kwargs:None
sys.modules['app.credentials']=stub
from app.demo_activation_api import router
engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
Base.metadata.create_all(engine)
app=FastAPI(dependencies=[Depends(enforce_access)]);app.include_router(router)
def getdb():
 with Session(engine) as db: yield db
app.dependency_overrides[get_session]=getdb
os.environ['CS4398_DEMO_ACTIVATION_TOKEN']='testtoken'
with TestClient(app,client=('127.0.0.1',12345)) as client:
 assert client.post('/api/v1/demo/setup-four').status_code==401
 head={'X-Demo-Token':'testtoken'}
 for _ in range(2):
  result=client.post('/api/v1/demo/setup-four',headers=head)
  assert result.status_code==200,result.text
  assert [n['state'] for n in result.json()['devices']]==['up','up','up','down']
 with Session(engine) as db:
  devices=db.scalars(select(Device)).all();assert len(devices)==4,len(devices)
  assert len(db.scalars(select(TopologyLink)).all())==3
  standby=db.scalar(select(Device).where(Device.name=='Standby-R4'))
  assert standby.ssh_port==2252
  assert db.get(DeviceState,standby.id).state=='down'
 result=client.post('/api/v1/demo/activate-standby',headers=head)
 assert result.status_code==200,result.text
 with Session(engine) as db:
  standby=db.scalar(select(Device).where(Device.name=='Standby-R4'))
  assert db.get(DeviceState,standby.id).state=='up'
 assert client.post('/api/v1/demo/activate-standby',headers=head).status_code==200
 with Session(engine) as db: assert len(db.scalars(select(Device)).all())==4
print('PASS four inventory rows, three up, one disabled, topology, activation, idempotence')
"""
  result=subprocess.run([sys.executable,'-c',code],cwd=repo,capture_output=True,text=True)
  self.assertEqual(result.returncode,0,result.stdout+result.stderr)
