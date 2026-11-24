"""Frontend startup sanity checks for the CS4398 incident integration."""
from pathlib import Path
import argparse, sys

def check(repo):
    f=repo/'web/src/pages/Network.tsx'
    if not f.is_file(): raise RuntimeError(f'Network page not found: {f}')
    s=f.read_text()
    q='  const devicesQuery = useApi(() => api.listDevices(), [])'
    feed='  // CS4398_INCIDENT_FEED_V5'
    if feed in s:
        if s.count(q)!=1: raise RuntimeError('Expected one devicesQuery declaration')
        if s.index(q)>s.index(feed):
            raise RuntimeError('White screen regression: incident effect uses devicesQuery before initialization')
        if '}, [scope, devicesQuery.data])' not in s:
            raise RuntimeError('Incident effect dependencies are unexpectedly changed')
    return 'Network frontend initialization order: PASS'

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--repo',type=Path,default=Path.home()/'Documents/capstone')
    args=p.parse_args()
    try: print(check(args.repo))
    except Exception as exc: print('ERROR:',exc,file=sys.stderr);sys.exit(1)
