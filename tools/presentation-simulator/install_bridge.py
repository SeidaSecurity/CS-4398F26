"""Minimal, reversible, opt-in API bridge installation for CS4398."""
from __future__ import annotations
import argparse
import shutil
from pathlib import Path

MARKER = 'from app.demo_metrics_adapter import fetch_demo_metrics'
STATE_MARKER = 'def get_demo_state():'
ACTIVATION_MARKER = 'from app.demo_activation_api import router as demo_activation_router'


def install(repo: Path) -> str:
    project = repo / 'app'
    monitoring = project / 'monitoring.py'
    adapter = project / 'demo_metrics_adapter.py'
    source = Path(__file__).parent / 'bridge' / 'demo_metrics_adapter.py'
    if not monitoring.is_file() or not (repo / 'web' / 'package.json').is_file():
        raise RuntimeError(f'Not a CS4398 repository: {repo}')
    old = monitoring.read_text()
    if MARKER in old:
        if STATE_MARKER in old:
            return 'Bridge already installed with scenario-state API; no changes made.'
        # Upgrade previous bridge while preserving prior metrics implementation.
        updated = old.replace(MARKER, 'from app.demo_metrics_adapter import fetch_demo_metrics, fetch_demo_state', 1)
        updated += '\n\n@router.get("/demo-state")\ndef get_demo_state():\n    return fetch_demo_state() or {"running": False, "active_warnings": [], "active_warning_count": 0, "telemetry_source": "unavailable"}\n'
        shutil.copy2(monitoring, monitoring.with_suffix('.py.cs4398-before-state-upgrade.bak'))
        adapter.write_bytes(source.read_bytes())
        monitoring.write_text(updated)
        compile(updated, str(monitoring), 'exec')
        return 'Existing metrics API bridge upgraded with read-only demo-state endpoint.' 
    if 'from app.database import get_session' not in old:
        raise RuntimeError('Monitoring API source changed: import anchor missing. No files changed.')
    if old.count('    buckets = sample_buckets(session, window)') != 1:
        raise RuntimeError('Network metrics anchor is not unique; no files changed.')
    if old.count('    buckets = sample_buckets(session, window, device_id)') != 1:
        raise RuntimeError('Device metrics anchor is not unique; no files changed.')
    new = old.replace('from app.database import get_session',
                      'from app.demo_metrics_adapter import fetch_demo_metrics, fetch_demo_state' + '\nfrom app.database import get_session', 1)
    new = new.replace('    buckets = sample_buckets(session, window)',
                      '    demo = fetch_demo_metrics("network", window)\n'
                      '    if demo is not None:\n'
                      '        return NetworkMetrics.model_validate(demo)\n'
                      '    buckets = sample_buckets(session, window)', 1)
    new = new.replace('    buckets = sample_buckets(session, window, device_id)',
                      '    demo = fetch_demo_metrics("device", window, session.get(Device, device_id).name)\n'
                      '    if demo is not None:\n'
                      '        return DeviceMetrics.model_validate(demo)\n'
                      '    buckets = sample_buckets(session, window, device_id)', 1)
    new += '\n\n@router.get("/demo-state")\ndef get_demo_state():\n    return fetch_demo_state() or {"running": False, "active_warnings": [], "active_warning_count": 0, "telemetry_source": "unavailable"}\n'
    # Keep the exact original in a nontracked .bak path. Git can also undo the change.
    backup = monitoring.with_suffix('.py.cs4398-before-demo.bak')
    if backup.exists():
        raise RuntimeError(f'Backup already exists: {backup}; no files changed.')
    shutil.copy2(monitoring, backup)
    try:
        adapter.write_bytes(source.read_bytes())
        monitoring.write_text(new)
        compile(new, str(monitoring), 'exec')
        compile(adapter.read_text(), str(adapter), 'exec')
    except Exception:
        shutil.copy2(backup, monitoring)
        if adapter.exists():
            adapter.unlink()
        raise
    return f'API bridge installed. Original saved as {backup.name}'

def install_local_token_access(repo: Path) -> str:
    """Allow exactly two loopback/demo-token endpoints past cookie authentication."""
    auth = repo / 'app' / 'auth.py'
    old = auth.read_text()
    marker = 'CS4398_FOUR_DEVICE_LOCALHOST_TOKEN_GUARD'
    if marker in old:
        return 'Scoped demo access already installed.'
    anchor = '    user = current_user(request, db)  # raises 401 when not logged in'
    if old.count(anchor) != 1:
        raise RuntimeError('Auth anchor missing: refusing to install')
    block = """    # CS4398_FOUR_DEVICE_LOCALHOST_TOKEN_GUARD (opt-in; never bypass other routes)
    if method == "POST" and path in ("/api/v1/demo/setup-four", "/api/v1/demo/activate-standby"):
        import hmac
        secret = os.getenv("CS4398_DEMO_ACTIVATION_TOKEN", "")
        token = request.headers.get("X-Demo-Token", "")
        if (secret and token and request.client and
                request.client.host in ("127.0.0.1", "::1") and
                hmac.compare_digest(secret, token)):
            return
"""
    new = old.replace(anchor, block+anchor, 1)
    compile(new, str(auth), 'exec')
    shutil.copy2(auth, auth.with_name('auth.py.cs4398-before-four-demo.bak'))
    auth.write_text(new)
    return 'Two local token-authenticated setup routes enabled; all other access unchanged.'


def install_activation(repo: Path) -> str:
    main = repo / 'app/main.py'
    endpoint = repo / 'app/demo_activation_api.py'
    source = Path(__file__).parent / 'bridge/demo_activation_api.py'
    old = main.read_text()
    if ACTIVATION_MARKER not in old:
        anchor = 'from app.syslog import SyslogReceivers, list_logs'
        if anchor not in old:
            raise RuntimeError('Cannot safely add activation API: main.py anchor missing')
        old = old.replace(anchor, anchor + '\n' + ACTIVATION_MARKER, 1)
        anchor2 = 'app = FastAPI('
        if anchor2 not in old:
            raise RuntimeError('Cannot safely add activation API: FastAPI constructor missing')
        # include the router after all app initialization (end of module)
        old += '\n\n# Optional localhost-only capstone presentation activation route.\napp.include_router(demo_activation_router)\n'
        compile(old, str(main), 'exec')
        shutil.copy2(main, main.with_name('main.py.cs4398-before-activation.bak'))
        main.write_text(old)
    endpoint.write_bytes(source.read_bytes())
    compile(endpoint.read_text(), str(endpoint), 'exec')
    return 'Opt-in activation API installed.'

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--repo', type=Path, default=Path.home() / 'Documents' / 'capstone')
    args = p.parse_args()
    print(install(args.repo))
    print(install_local_token_access(args.repo))
    print(install_activation(args.repo))
