#!/bin/bash
# CS 4398 Network Management Application: local Mac launcher
# Run from Finder (right-click > Open) or: bash Start_Capstone_With_Router.command
set -u

ROOT="${CAPSTONE_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
BUNDLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAB_DIR="$HOME/.cs4398-capstone-lab"
EMULATOR_PID=""
WORKER2_PID=""
WORKER3_PID=""
STANDBY_PID=""
WORKER_PID=""
SIMULATOR_PID=""

URL="http://127.0.0.1:5173"
API_URL="http://127.0.0.1:8000"
API_PID=""
WEB_PID=""

cleanup() {
  echo
  echo "Stopping local capstone services..."
  if [ -n "$WEB_PID" ]; then kill "$WEB_PID" 2>/dev/null || true; fi
  if [ -n "$EMULATOR_PID" ]; then kill "$EMULATOR_PID" 2>/dev/null || true; fi
  if [ -n "$WORKER2_PID" ]; then kill "$WORKER2_PID" 2>/dev/null || true; fi
  if [ -n "$WORKER3_PID" ]; then kill "$WORKER3_PID" 2>/dev/null || true; fi
  if [ -n "$STANDBY_PID" ]; then kill "$STANDBY_PID" 2>/dev/null || true; fi
  if [ -n "$WORKER_PID" ]; then kill "$WORKER_PID" 2>/dev/null || true; fi
  if [ -n "$SIMULATOR_PID" ]; then kill "$SIMULATOR_PID" 2>/dev/null || true; fi
  if [ -n "$API_PID" ]; then kill "$API_PID" 2>/dev/null || true; fi
  wait 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 130' INT TERM

fail() {
  echo
  echo "ERROR: $*"
  echo "Press Enter to close this window."
  read -r _ < /dev/tty || true
  exit 1
}

if [ ! -f "$ROOT/pyproject.toml" ] || [ ! -f "$ROOT/web/package.json" ]; then
  fail "Couldn't find the project at $ROOT. Set CAPSTONE_DIR to the actual repo folder or clone it to ~/Documents/capstone."
fi
cd "$ROOT" || fail "Could not open $ROOT"
echo "CS 4398 — Live App + Virtual SSH Router"
echo "Using repository: $ROOT"
echo "The router has a simulated IOS-like CLI, not Cisco IOS/CML."
echo
MODE=2

command -v node >/dev/null 2>&1 || fail "Node.js not installed. Install Node 22.12+ or 20.19+ from https://nodejs.org/ and run again."
command -v npm >/dev/null 2>&1 || fail "npm not installed. Install Node.js first."
node -e 'let [major,minor]=process.versions.node.split(".").map(Number);if (!((major===20&&minor>=19)||(major===22&&minor>=12)||(major>22))) process.exit(1)' || fail "Unsupported Node version $(node --version). Install Node 22.12+ or Node 20.19+."

if command -v lsof >/dev/null 2>&1; then
  if lsof -nP -iTCP:5173 -sTCP:LISTEN 2>/dev/null | grep -q LISTEN; then
    fail "Port 5173 is in use. Stop the other dev server first."
  fi
fi

if [ "$MODE" = "2" ]; then
  if command -v lsof >/dev/null 2>&1; then
    if lsof -nP -iTCP:8000 -sTCP:LISTEN 2>/dev/null | grep -q LISTEN; then
      fail "Port 8000 is in use. Stop the other API server first."
    fi
  fi
  echo
  echo "LIVE MODE: This uses a local SQLite database and IOS-like SSH emulator, not Cisco CML."
  echo "The initial admin is created on first launch only."
  printf 'Admin username [admin]: '
  read -r ADMIN_USERNAME
  ADMIN_USERNAME=${ADMIN_USERNAME:-admin}
  if [ ! -f capstone_presentation.db ]; then
    echo "Choose an admin password (8–64 characters, not a common password)."
    printf 'Admin password (input hidden): '
    IFS= read -r -s ADMIN_PASSWORD
    echo
    if [ "${#ADMIN_PASSWORD}" -lt 8 ] || [ "${#ADMIN_PASSWORD}" -gt 64 ]; then
      fail "Password must be 8–64 characters."
    fi
  else
    echo "Using existing capstone_presentation.db. Log in with the password you chose on its first launch."
    ADMIN_PASSWORD=""
  fi
  if [ ! -x .venv/bin/python ]; then
    echo "Creating a Python virtual environment..."
    python3 -m venv .venv || fail "Python venv creation failed. Install Python 3.11+ and retry."
  fi
  if ! .venv/bin/python -c 'import uvicorn, fastapi, sqlalchemy, dnslib, netmiko, icmplib, pysnmp' 2>/dev/null; then
    echo "Installing backend dependencies (internet required on first run)..."
    .venv/bin/python -m pip install -e '.[dev]' || fail "Python dependencies could not be installed. Check internet and your Python version."
  fi
fi

# Store test secrets outside the Git repository so they are not committed.
umask 077
mkdir -p "$LAB_DIR" || fail "Could not create $LAB_DIR"
chmod 700 "$LAB_DIR" 2>/dev/null || true
if [ ! -s "$LAB_DIR/router_password" ]; then
  .venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(18))' > "$LAB_DIR/router_password" || fail "Could not generate router password"
fi
chmod 600 "$LAB_DIR/router_password" 2>/dev/null || true
export VROUTER_PASSWORD="$(cat "$LAB_DIR/router_password")"
if [ -z "${NETMGR_SECRET_KEY:-}" ]; then
  if [ ! -s "$LAB_DIR/fernet.key" ]; then
    .venv/bin/python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())' > "$LAB_DIR/fernet.key" || fail "Could not generate credential encryption key"
  fi
  chmod 600 "$LAB_DIR/fernet.key" 2>/dev/null || true
  export NETMGR_SECRET_KEY="$(cat "$LAB_DIR/fernet.key")"
fi

if command -v lsof >/dev/null 2>&1; then
  if lsof -nP -iTCP:2222 -sTCP:LISTEN 2>/dev/null | grep -q LISTEN; then
    fail "Emulator port 2222 is already in use. Stop the old virtual router first."
  fi
fi

if [ ! -d web/node_modules ]; then
  echo "Installing frontend packages (internet required on first run)..."
  (cd web && npm ci) || fail "npm ci failed. Check internet, Node version and npm errors."
fi

LOGDIR=$(mktemp -d "${TMPDIR:-/tmp}/cs4398.XXXXXX") || fail "Could not create a temporary log directory"
echo "Local service logs: $LOGDIR"

echo "Starting Primary-R1 SSH emulator at 127.0.0.1:2222 ..."
.venv/bin/python "$BUNDLE_DIR/virtual_router.py" --host 127.0.0.1 --port 2222 --username labadmin --hostname Primary-R1 --state-dir "$LAB_DIR/demo-primary-v4" >"$LOGDIR/router.log" 2>&1 &
EMULATOR_PID=$!
EMU_READY=0
for i in 1 2 3 4 5 6 7 8 9 10; do
  if .venv/bin/python -c 'import socket; s=socket.create_connection(("127.0.0.1",2222),timeout=1); b=s.recv(30); s.close(); raise SystemExit(0 if b.startswith(b"SSH-") else 1)' >/dev/null 2>&1; then EMU_READY=1; break; fi
  if ! kill -0 "$EMULATOR_PID" 2>/dev/null; then break; fi
  sleep 1
done
if [ "$EMU_READY" -ne 1 ]; then
  echo "Emulator log:"; tail -n 40 "$LOGDIR/router.log" || true
  fail "Virtual router did not start."
fi

# Independent scenario process: localhost requests + standby SSH emulator.
# This does not modify any project database or generate real CPU resource exhaustion.
if ! grep -q 'from app.demo_metrics_adapter import fetch_demo_metrics' "$ROOT/app/monitoring.py"; then
  fail "Run Install_API_Bridge.command once before launching this scenario."
fi
for P in 2232 2242 2252 8765; do
  if lsof -nP -iTCP:"$P" -sTCP:LISTEN 2>/dev/null | grep -q LISTEN; then
    fail "Port $P is in use. Stop the previous simulator instance first."
  fi
done
# Three operational devices and one disabled standby, each with a reachable SSH CLI.
for SPEC in 'Worker-R2:2232' 'Worker-R3:2242'; do
  NAME="${SPEC%%:*}"; PORT="${SPEC##*:}"
  DIR="$LAB_DIR/demo-v4-$NAME"
  mkdir -p "$DIR"
  .venv/bin/python "$BUNDLE_DIR/virtual_router.py" --host 127.0.0.1 --port "$PORT" --username labadmin --hostname "$NAME" --state-dir "$DIR" >"$LOGDIR/$NAME.log" 2>&1 &
  if [ "$PORT" = 2232 ]; then WORKER2_PID=$!; else WORKER3_PID=$!; fi
done
STANDBY_DIR="$LAB_DIR/demo-v4-Standby-R4"
mkdir -p "$STANDBY_DIR"
# Reset ONLY the demo standby interface, preserving presentation credentials/database.
.venv/bin/python - "$STANDBY_DIR/router.json" <<'PYSEED'
import json,sys
from pathlib import Path
p=Path(sys.argv[1]);p.parent.mkdir(parents=True,exist_ok=True)
p.write_text(json.dumps({'hostname':'Standby-R4','interfaces':{
 'GigabitEthernet0/0':{'description':'SSH management (always reachable)','ip_address':None,'shutdown':False},
 'GigabitEthernet0/1':{'description':'Standby load-sharing interface','ip_address':None,'shutdown':True}},
 'extra_lines':[]},indent=2))
PYSEED
chmod 600 "$STANDBY_DIR/router.json"
echo "Starting disabled Standby-R4 SSH management on 127.0.0.1:2252 ..."
.venv/bin/python "$BUNDLE_DIR/virtual_router.py" --host 127.0.0.1 --port 2252 --username labadmin --hostname Standby-R4 --state-dir "$STANDBY_DIR" >"$LOGDIR/standby.log" 2>&1 &
STANDBY_PID=$!
WORKER_DIR="$LAB_DIR/demo-v4-no-extra-worker"
mkdir -p "$WORKER_DIR"
if [ ! -s "$LAB_DIR/demo_token" ]; then
  .venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(32))' > "$LAB_DIR/demo_token"
fi
chmod 600 "$LAB_DIR/demo_token"
export CS4398_DEMO_ACTIVATION_TOKEN="$(cat "$LAB_DIR/demo_token")"
echo "Starting isolated workload simulator on 127.0.0.1:8765 ..."
.venv/bin/python "$BUNDLE_DIR/simulator.py" --standby-state "$STANDBY_DIR/router.json" --worker-state-dir "$WORKER_DIR" >"$LOGDIR/simulator.log" 2>&1 &
SIMULATOR_PID=$!
DEMO_READY=0
for i in 1 2 3 4 5 6 7 8 9 10; do
  if curl -fsS --max-time 1 http://127.0.0.1:8765/health >/dev/null 2>&1 && .venv/bin/python -c 'import socket;s=socket.create_connection(("127.0.0.1",2252),timeout=1);s.close()' >/dev/null 2>&1; then DEMO_READY=1;break;fi
  sleep 1
done
if [ "$DEMO_READY" -ne 1 ]; then
  tail -n 30 "$LOGDIR/simulator.log" "$LOGDIR/standby.log" || true
  fail "Simulator or standby router did not start."
fi

echo "Checking all four router SSH endpoints ..."
for PORT in 2222 2232 2242 2252; do
  OK=0
  for ATTEMPT in 1 2 3 4 5; do
    if .venv/bin/python - "$PORT" <<'PYPORT'
import socket,sys
port=int(sys.argv[1])
with socket.create_connection(('127.0.0.1',port),timeout=1) as s:
    assert s.recv(32).startswith(b'SSH-')
PYPORT
    then OK=1;break;fi
    sleep 1
  done
  if [ "$OK" -ne 1 ]; then
    echo "SSH endpoint on $PORT was not ready."
    tail -n 20 "$LOGDIR/standby.log" "$LOGDIR/Worker-R2.log" "$LOGDIR/Worker-R3.log" "$LOGDIR/router.log" || true
    fail "Cannot start presentation with missing SSH device port $PORT."
  fi
done

if [ "$MODE" = "2" ]; then
  echo "Starting FastAPI backend on $API_URL ..."
  export DATABASE_URL='sqlite:///./capstone_presentation.db'
  export ADMIN_USERNAME ADMIN_PASSWORD
  export COOKIE_SECURE=false
  export MONITORING_ENABLED=false
  export POLL_INTERVAL_SECONDS=15
  export SYSLOG_ENABLED=true
  export SYSLOG_HOST=127.0.0.1
  export SYSLOG_UDP_PORT=1514
  export SYSLOG_TCP_PORT=1515
  export CS4398_DEMO_METRICS_URL=http://127.0.0.1:8765
  export DNS_ENABLED=false
  export DHCP_ENABLED=false
  export SESSION_IDLE_MINUTES=30
  .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 >"$LOGDIR/api.log" 2>&1 &
  API_PID=$!
  API_READY=0
  for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
    if curl -fsS --max-time 2 "$API_URL/health" >/dev/null 2>&1; then API_READY=1; break; fi
    if ! kill -0 "$API_PID" 2>/dev/null; then break; fi
    sleep 1
  done
  if [ "$API_READY" -ne 1 ]; then
    echo "Backend log:"; tail -n 40 "$LOGDIR/api.log" || true
    fail "FastAPI did not become healthy."
  fi
  echo "Creating/updating exactly four presentation Inventory devices and topology links ..."
  if ! curl -fsS --retry 8 --retry-delay 1 --max-time 5 -X POST \
      -H "X-Demo-Token: $CS4398_DEMO_ACTIVATION_TOKEN" \
      -H 'Content-Type: application/json' -d '{}' \
      "$API_URL/api/v1/demo/setup-four"; then
    echo; tail -n 50 "$LOGDIR/api.log" || true
    fail "Four-device Inventory setup failed."
  fi
  echo
  echo "Backend ready. API documentation: $API_URL/docs"
fi

echo "Checking frontend dependencies and compiling React dashboard..."
if [ ! -d web/node_modules ] || [ ! -x web/node_modules/.bin/vite ]; then
  (cd web && npm ci --no-audit --no-fund) || fail "npm ci failed; frontend dependencies are missing."
fi
.venv/bin/python "$BUNDLE_DIR/check_frontend.py" --repo "$ROOT" || fail "React source failed render-safety checks."
(cd web && npm run build) || fail "React/TypeScript production build failed. See the error above instead of opening a blank page."
echo "Starting React dashboard on $URL ..."
if [ "$MODE" = "2" ]; then
  (cd web && VITE_API_MODE=live npm run dev -- --host 127.0.0.1 --port 5173 --strictPort) >"$LOGDIR/web.log" 2>&1 &
else
  (cd web && VITE_API_MODE=mock npm run dev -- --host 127.0.0.1 --port 5173 --strictPort) >"$LOGDIR/web.log" 2>&1 &
fi
WEB_PID=$!
WEB_READY=0
for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
  if curl -fsS --max-time 2 "$URL" >/dev/null 2>&1; then WEB_READY=1; break; fi
  if ! kill -0 "$WEB_PID" 2>/dev/null; then break; fi
  sleep 1
done
if [ "$WEB_READY" -ne 1 ]; then
  echo "Frontend log:"; tail -n 40 "$LOGDIR/web.log" || true
  fail "The frontend did not start."
fi

echo
echo "=============================================================="
echo "APP READY: $URL"
if [ "$MODE" = "1" ]; then
  echo "TEST LOGIN: username admin, any non-empty password"
  echo "All displayed devices/data are simulated; changes are not saved to a real backend."
else
  echo "LIVE LOGIN: username $ADMIN_USERNAME, your chosen admin password"
  echo "Backend: $API_URL     API docs: $API_URL/docs"
  echo "Database: $ROOT/capstone_presentation.db"
  echo "Monitoring: deterministic modeled telemetry only (polling off to preserve disabled status)"
  echo "--------------------------------------------------------------"
  echo "ADD DEVICE from Inventory -> Devices -> Add device:"
  echo "Name:          Primary-R1"
  echo "Management IP: 127.0.0.1"
  echo "Platform:      cisco_ios"
  echo "SSH port:      2222"
  echo "SSH username:  labadmin"
  echo "SSH password:  $VROUTER_PASSWORD"
  echo "Enable secret: (leave blank)"
  echo "--------------------------------------------------------------"
  echo "SSH/Netmiko diagnostic command in a new Terminal window:"
  echo "  cd $ROOT && .venv/bin/python $BUNDLE_DIR/verify_connection.py"
  echo "WARNING: Ping to 127.0.0.1 will work even if the emulator stops."
fi
echo "=============================================================="
echo "SCENARIO CONTROLLER: http://127.0.0.1:8765"
echo "DEVICES: Primary-R1 2222, Worker-R2 2232, Worker-R3 2242, Standby-R4 2252"
echo "Standby OFF by default. Push to Standby-R4:"
echo "  interface GigabitEthernet0/1"
echo "  no shutdown"
echo "Presentation metrics are SIMULATED, not actual device SNMP telemetry."
echo "Press Control+C in this terminal to stop the app and emulator."
echo "=============================================================="
if command -v open >/dev/null 2>&1; then open "$URL" || true; open http://127.0.0.1:8765 || true; fi
wait "$WEB_PID"
