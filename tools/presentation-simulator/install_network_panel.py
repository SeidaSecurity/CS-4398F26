"""Add a read-only demo alert panel to an existing CS4398 Network activity page."""
from __future__ import annotations
import argparse
import shutil
import subprocess
from pathlib import Path

MARKER = 'CS4398_DEMO_WARNINGS_PANEL'

def enable_fast_refresh(repo: Path) -> str:
    changed=[]
    for name in ('Network.tsx','Devices.tsx'):
        page=repo/'web/src/pages'/name
        source=page.read_text()
        # These are intentionally scoped to the opt-in demo installation, not main.
        if name == 'Network.tsx' and "useState<TimeWindow>('24h')" in source:
            source = source.replace("useState<TimeWindow>('24h')", "useState<TimeWindow>('1h')", 1)
        if 'setInterval(reload, 60_000)' in source:
            page.write_text(source.replace('setInterval(reload, 60_000)', 'setInterval(reload, 3_000)', 1))
            changed.append(name)
    return ('Fast refresh: '+', '.join(changed)+'. ' if changed else '')


def install(repo: Path) -> str:
    page = repo / 'web/src/pages/Network.tsx'
    patch = Path(__file__).parent / 'Network_Dashboard.patch'
    if not page.exists():
        raise RuntimeError('Network.tsx not found')
    source = page.read_text()
    if MARKER in source:
        return enable_fast_refresh(repo) + enhance_live_incident_charts(repo) + ' Demo warning panel already installed.'
    if 'Network activity' not in source or 'Log severity' not in source:
        check = subprocess.run(['git','apply','--check',str(patch)],cwd=repo,capture_output=True,text=True)
        if check.returncode == 0:
            applied = subprocess.run(['git','apply',str(patch)],cwd=repo,capture_output=True,text=True)
            if applied.returncode != 0:
                raise RuntimeError('Network activity patch failed: '+applied.stderr)
            source = page.read_text()
        else:
            raise RuntimeError('Your Network page lacks the Network activity update, and its patch could not be applied safely. No existing files overwritten. Check `git status`, then apply the previously downloaded Network Dashboard update first.')
    original = source
    anchor = "  const [activityNow, setActivityNow] = useState(Date.now)"
    if source.count(anchor)!=1:
        raise RuntimeError('Network page changed; hook anchor not found exactly once.')
    addition = '''  // CS4398_DEMO_WARNINGS_PANEL: opt-in, API-only status from isolated localhost simulator.
  const [demo, setDemo] = useState<{ running: boolean; standby_enabled?: boolean; active_warnings: Array<{ source: string; severity: string; message: string }>; telemetry_source?: string } | null>(null)
  useEffect(() => {
    let disposed = false
    async function pollDemo() {
      try {
        const response = await fetch('/api/v1/monitoring/demo-state', { credentials: 'same-origin' })
        if (!response.ok) { if (!disposed) setDemo(null); return }
        const data = await response.json()
        if (!disposed) setDemo(data.telemetry_source === 'synthetic localhost scenario' ? data : null)
      } catch { if (!disposed) setDemo(null) }
    }
    void pollDemo()
    const timer = setInterval(() => { void pollDemo() }, 3000)
    return () => { disposed = true; clearInterval(timer) }
  }, [])
'''
    source=source.replace(anchor, anchor+'\n'+addition,1)
    anchor2='      <RightPanel>'
    if source.count(anchor2)!=1:
        raise RuntimeError('Right sidebar anchor missing or duplicate')
    panel='''      <RightPanel>
        {demo && <PanelSection title="Demo scenario alerts (simulated)" icon={Warning}>
          {demo.active_warnings.length ? demo.active_warnings.map((item, i) => (
            <div key={i} role="alert" style={{ marginBottom: 8, borderRadius: 8, padding: '10px 12px', background: '#fff2df', border: '1px solid #e1a052', color: '#713d07', fontSize: 12 }}>
              <strong>{item.severity.toUpperCase()} — {item.source}</strong>
              <div style={{ marginTop: 4 }}>{item.message}</div>
            </div>
          )) : <div role="status" style={{ padding: 8, fontSize: 12, color: 'var(--green-800)' }}>
            {demo.standby_enabled && demo.running ? 'Standby enabled — overload resolved automatically.' : 'No active demo overload warnings.'}
          </div>}
          <div style={{ fontSize: 11, color: 'var(--gray-600)', marginTop: 6 }}>
            Synthetic scenario status via the capstone monitoring API; not hardware SNMP alerts.
          </div>
        </PanelSection>}
'''
    source=source.replace(anchor2,panel,1)
    backup=page.with_name('Network.tsx.cs4398-before-demo-panel.bak')
    if backup.exists():
        raise RuntimeError(f'Backup already exists: {backup}')
    shutil.copy2(page,backup)
    page.write_text(source)
    return enable_fast_refresh(repo) + enhance_live_incident_charts(repo) + ' Network activity + severity graphs and live demo warnings panel installed.'

LIVE_CHARTS = '        {demo && <>\n          <ChartSection title="Live network activity (last 2 minutes)" chip={<Pill tone="gray" icon={Article}>{liveActivity.syslogCount + liveActivity.auditCount} events</Pill>} legend={[{ label: \'Syslog\', color: brand }, { label: \'Config changes\', color: green, dashed: true }]} yTicks={[liveActivity.maximum, Math.round(liveActivity.maximum / 2), 0].map(String)} xLabels={[\'-120s\', \'-90s\', \'-60s\', \'-30s\', \'now\']}>\n            <TimeSeries series={[{ data: liveActivity.syslog, color: brand, type: \'step\', fill: true }, { data: liveActivity.audit, color: green, type: \'step\', dashed: true }]} domain={[0, liveActivity.maximum]} />\n          </ChartSection>\n          <ChartSection title="Live warnings / errors (last 2 minutes)" legend={[{ label: \'Errors\', color: red }, { label: \'Warnings\', color: \'var(--amber-800)\', dashed: true }]} yTicks={[liveActivity.severityMaximum, Math.round(liveActivity.severityMaximum / 2), 0].map(String)} xLabels={[\'-120s\', \'-90s\', \'-60s\', \'-30s\', \'now\']}>\n            <TimeSeries series={[{ data: liveActivity.errorSeries, color: red, type: \'step\', fill: true }, { data: liveActivity.warningSeries, color: \'var(--amber-800)\', type: \'step\', dashed: true }]} domain={[0, liveActivity.severityMaximum]} />\n          </ChartSection>\n        </>}\n'

def enhance_live_incident_charts(repo: Path) -> str:
    """Show short-term rates from persisted logs in addition to 1h history."""
    page = repo / 'web/src/pages/Network.tsx'
    source = page.read_text()
    if 'CS4398_LIVE_INCIDENT_TIMELINE' in source:
        return ' Live incident charts already installed.'
    before = '  const activity = networkActivity(logsQuery.data ?? [], auditsQuery.data ?? [], activityNow, windowMs[window], selectedDevice)'
    if source.count(before) != 1:
        raise RuntimeError('Live incident timeline requires the original activity calculation')
    source = source.replace(before, before + "\n  // CS4398_LIVE_INCIDENT_TIMELINE: persisted syslog, 2.5-second buckets.\n  const liveActivity = networkActivity(logsQuery.data ?? [], auditsQuery.data ?? [], activityNow, 120_000, selectedDevice)", 1)
    chart = '        <ChartSection title="Network activity"'
    if source.count(chart) != 1:
        raise RuntimeError('Live incident timeline chart anchor missing')
    source = source.replace(chart, LIVE_CHARTS + chart, 1)
    page.write_text(source)
    return ' Live 2-minute persisted syslog and warning/error charts installed.'

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--repo',type=Path,default=Path.home()/'Documents/capstone')
    print(install(p.parse_args().repo))
