#!/bin/bash
# Non-destructive observable-state diagnostics for the Mac presentation rehearsal.
set -euo pipefail
ROOT="${CAPSTONE_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
DB="$ROOT/capstone_presentation.db"
echo '=== CS4398 FOUR-DEVICE PRESENTATION CHECK ==='
echo 'Independent controller:'
curl --fail --silent --show-error --max-time 3 http://127.0.0.1:8765/state || true
echo; echo 'Capstone backend health:'
curl --fail --silent --show-error --max-time 3 http://127.0.0.1:8000/health || true
echo; echo 'Monitoring API requires dashboard login; check its graphs at http://127.0.0.1:5173' 
echo
python3 - "$DB" <<'PY'
import sys,sqlite3
from pathlib import Path
p=Path(sys.argv[1])
print('Presentation database:', p)
if not p.exists():
 print('FAIL: missing presentation DB. Start the v4 launcher first.');sys.exit(1)
connection=sqlite3.connect(f'file:{p}?mode=ro',uri=True)
connection.row_factory=sqlite3.Row
names=('Primary-R1','Worker-R2','Worker-R3','Standby-R4')
rows=connection.execute('SELECT d.id,d.name,d.ssh_port,s.state FROM devices d LEFT JOIN device_states s ON s.device_id=d.id WHERE d.name IN (?,?,?,?) ORDER BY d.name',names).fetchall()
print('\nInventory and device status:')
for r in rows:print(' ',r['name'],r['ssh_port'],r['state'])
if len(rows)!=4:
 print('FAIL: expected four demo Inventory records, got',len(rows));sys.exit(2)
states={r['name']:r['state'] for r in rows}
if any(states[n]!='up' for n in names[:3]):
 print('FAIL: all three active demo workers must be Up');sys.exit(2)
if states['Standby-R4'] not in ('up','down'):
 print('FAIL: standby has no valid device state');sys.exit(2)
links=connection.execute('SELECT COUNT(*) FROM topology_links').fetchone()[0]
print('\nTopology links:',links, '(expect at least 3)')
if links<3:
 print('FAIL: topology is missing expected links');sys.exit(2)
logrows=connection.execute("SELECT severity,count(*) AS n FROM log_records WHERE body LIKE '%DEMO SIMULATED%' GROUP BY severity ORDER BY severity").fetchall()
print('\nPersisted demo syslog severity counts:', {row['severity']:row['n'] for row in logrows})
if not logrows:
 print('No simulated log events yet: press Generate Request Spike and check again.')
else:
 for row in connection.execute("SELECT timestamp,source,severity,body FROM log_records WHERE body LIKE '%DEMO SIMULATED%' ORDER BY id DESC LIMIT 5"):
  print(' ',tuple(row))
print('\nPASS: four devices, current states and topology records verified. Standby state:',states['Standby-R4'])
PY
