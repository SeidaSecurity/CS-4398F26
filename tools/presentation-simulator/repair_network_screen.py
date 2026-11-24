"""Repair an already installed v5 UI and prevent the empty-screen regression.

The v5 installer inserted a React useEffect above its referenced devicesQuery.
This is a temporal-dead-zone error because hook dependency arrays execute
synchronously while React renders the page. Move the query above the effect.
"""
from __future__ import annotations
import argparse
from pathlib import Path

QUERY = '  const devicesQuery = useApi(() => api.listDevices(), [])'
FEED = '  // CS4398_INCIDENT_FEED_V5'

def repair(repo: Path) -> str:
    page = repo / 'web/src/pages/Network.tsx'
    if not page.is_file():
        raise RuntimeError(f'Missing {page}')
    source = page.read_text()
    if FEED not in source:
        return 'Incident feed not installed yet; no repair needed.'
    if source.count(QUERY) != 1 or source.count(FEED) != 1:
        raise RuntimeError('Unexpected Network.tsx layout; refusing to guess at a repair')
    a, b = source.index(QUERY), source.index(FEED)
    if a < b:
        return 'Device query already initialized before incident feed; safe.'
    source = source[:a] + source[a:].replace(QUERY+'\n','',1)
    b = source.index(FEED)
    source = source[:b] + QUERY+'\n' + source[b:]
    page.write_text(source)
    return 'Fixed Network.tsx: devicesQuery is initialized before the incident hook.'

if __name__ == '__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('--repo',type=Path,default=Path.home()/'Documents/capstone')
    print(repair(ap.parse_args().repo))
