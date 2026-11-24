"""Idempotent, narrowly scoped v5 API + UI integration on top of the v4 installer."""
from pathlib import Path
import argparse, shutil

MARKER = 'CS4398_INCIDENT_AGGREGATION_V5'

def install(repo: Path, bundle: Path) -> str:
    monitoring = repo/'app/monitoring.py'
    target = repo/'app/incident_activity_api.py'
    original = monitoring.read_text()
    if MARKER not in original:
        prefix = '# CS4398_INCIDENT_AGGREGATION_V5\nfrom app.incident_activity_api import install_incident_route\n'
        text = prefix + original + '\ninstall_incident_route(router)\n'
        # Python future imports must remain first; add after last import before router assignment
        text = original.replace('router = APIRouter(prefix="/api/v1/monitoring")',
                                'from app.incident_activity_api import install_incident_route  # CS4398_INCIDENT_AGGREGATION_V5\n\nrouter = APIRouter(prefix="/api/v1/monitoring")',1)
        text += '\ninstall_incident_route(router)\n'
        if MARKER not in text: raise RuntimeError('Monitoring API anchor missing')
        compile(text,str(monitoring),'exec')
        shutil.copy2(monitoring,monitoring.with_name('monitoring.py.cs4398-before-v5.bak'))
        monitoring.write_text(text)
    target.write_bytes((bundle/'bridge/incident_activity_api.py').read_bytes())
    page = repo/'web/src/pages/Network.tsx'
    s = page.read_text()
    if 'CS4398_INCIDENT_FEED_V5' not in s:
        anchor='  const devicesQuery = useApi(() => api.listDevices(), [])'
        if s.count(anchor)!=1: raise RuntimeError('Network page v5 state anchor missing')
        hooks='''  // CS4398_INCIDENT_FEED_V5 — read-only aggregation of persisted backend syslog.
  type IncidentBucket = { t: string; all: number; warnings: number; errors: number }
  type IncidentFeed = { buckets: IncidentBucket[]; total: number; warning_count: number; error_count: number; source: string }
  const [incidentFeed, setIncidentFeed] = useState<IncidentFeed | null>(null)
  useEffect(() => {
    let cancelled = false
    async function load() {
      const device = scope === 'all' ? '' : devicesQuery.data?.find(d => String(d.id) === scope)?.name ?? ''
      try {
        const query = new URLSearchParams({ seconds: '120' })
        if (device) query.set('source', device)
        const response = await fetch(`/api/v1/monitoring/incident-activity?${query}`, { credentials: 'same-origin' })
        if (!response.ok) throw new Error(`Incident API: ${response.status}`)
        const data: IncidentFeed = await response.json()
        if (!cancelled) setIncidentFeed(data.source === 'stored_syslog' ? data : null)
      } catch { if (!cancelled) setIncidentFeed(null) }
    }
    void load()
    const timer = setInterval(() => void load(), 3000)
    return () => { cancelled = true; clearInterval(timer) }
  }, [scope, devicesQuery.data])
'''
        # React evaluates dependency arrays during rendering. The query MUST be
        # initialized before the new effect reads devicesQuery.data.
        s=s.replace(anchor,anchor+'\n'+hooks,1)
        anchor2='  const memory = report?.kind === \'device\' ? report.metrics.memory : []'
        if s.count(anchor2)!=1: raise RuntimeError('Network page v5 data anchor missing')
        data='''  const incidentBuckets = incidentFeed?.buckets ?? []
  const incidentPoints = (key: 'all' | 'warnings' | 'errors') => incidentBuckets.map(b => ({t:b.t,value:b[key]}))
  const incidentMax = Math.max(1, ...incidentBuckets.map(b => b.all))
  const incidentSeverityMax = Math.max(1, ...incidentBuckets.map(b => b.errors + b.warnings))
'''
        s=s.replace(anchor2,data+anchor2,1)
        # V4 live panel uses capped 1000 logs; upgrade to persisted aggregates.
        s=s.replace('liveActivity.syslogCount + liveActivity.auditCount','incidentFeed?.total ?? liveActivity.syslogCount + liveActivity.auditCount')
        s=s.replace('liveActivity.maximum, Math.round(liveActivity.maximum / 2), 0','incidentFeed ? incidentMax : liveActivity.maximum, Math.round((incidentFeed ? incidentMax : liveActivity.maximum) / 2), 0')
        s=s.replace("{ data: liveActivity.syslog, color: brand, type: 'step', fill: true }", "{ data: incidentFeed ? incidentPoints('all') : liveActivity.syslog, color: brand, type: 'step', fill: true }")
        s=s.replace('domain={[0, liveActivity.maximum]}','domain={[0, incidentFeed ? incidentMax : liveActivity.maximum]}')
        s=s.replace('liveActivity.severityMaximum, Math.round(liveActivity.severityMaximum / 2), 0','incidentFeed ? incidentSeverityMax : liveActivity.severityMaximum, Math.round((incidentFeed ? incidentSeverityMax : liveActivity.severityMaximum) / 2), 0')
        s=s.replace("{ data: liveActivity.errorSeries, color: red, type: 'step', fill: true }", "{ data: incidentFeed ? incidentPoints('errors') : liveActivity.errorSeries, color: red, type: 'step', fill: true }")
        s=s.replace("{ data: liveActivity.warningSeries, color: 'var(--amber-800)', type: 'step', dashed: true }", "{ data: incidentFeed ? incidentPoints('warnings') : liveActivity.warningSeries, color: 'var(--amber-800)', type: 'step', dashed: true }")
        s=s.replace('domain={[0, liveActivity.severityMaximum]}','domain={[0, incidentFeed ? incidentSeverityMax : liveActivity.severityMaximum]}')
        # Make the primary Network activity / Log severity panels use the same
        # complete persisted incident rollup while the scenario is enabled.
        s=s.replace('title="Network activity" chip={<Pill tone="gray" icon={Article}>{activity.syslogCount + activity.auditCount} events</Pill>}',
                    'title="Network activity" chip={<Pill tone="gray" icon={Article}>{incidentFeed ? incidentFeed.total : activity.syslogCount + activity.auditCount} events</Pill>}')
        s=s.replace('yTicks={[activity.maximum, Math.round(activity.maximum / 2), 0].map(String)} xLabels={xLabels}',
                    'yTicks={[incidentFeed ? incidentMax : activity.maximum, Math.round((incidentFeed ? incidentMax : activity.maximum) / 2), 0].map(String)} xLabels={incidentFeed ? ["-120s", "-90s", "-60s", "-30s", "now"] : xLabels}')
        s=s.replace("{ data: activity.syslog, color: brand, type: 'step', fill: true }",
                    "{ data: incidentFeed ? incidentPoints('all') : activity.syslog, color: brand, type: 'step', fill: true }")
        s=s.replace('domain={[0, activity.maximum]}','domain={[0, incidentFeed ? incidentMax : activity.maximum]}')
        s=s.replace('yTicks={[activity.severityMaximum, Math.round(activity.severityMaximum / 2), 0].map(String)} xLabels={xLabels}',
                    'yTicks={[incidentFeed ? incidentSeverityMax : activity.severityMaximum, Math.round((incidentFeed ? incidentSeverityMax : activity.severityMaximum) / 2), 0].map(String)} xLabels={incidentFeed ? ["-120s", "-90s", "-60s", "-30s", "now"] : xLabels}')
        s=s.replace("{ data: activity.errorSeries, color: red, type: 'step', fill: true }",
                    "{ data: incidentFeed ? incidentPoints('errors') : activity.errorSeries, color: red, type: 'step', fill: true }")
        s=s.replace("{ data: activity.warningSeries, color: 'var(--amber-800)', type: 'step', dashed: true }",
                    "{ data: incidentFeed ? incidentPoints('warnings') : activity.warningSeries, color: 'var(--amber-800)', type: 'step', dashed: true }")
        s=s.replace('domain={[0, activity.severityMaximum]}','domain={[0, incidentFeed ? incidentSeverityMax : activity.severityMaximum]}')
        # Original longer history uses latest 1000, and becomes misleading at high rates.
        # Keep it explicitly historical, while last-2m panels use all persisted records.
        s=s.replace('Latest 1,000 syslog messages and 100 audit records are queried.', 'Recent individual messages are capped; the incident charts aggregate all stored events for the last two minutes.')
        # Alert panel professionalized, with explicit provenance
        s=s.replace('Demo scenario alerts (simulated)','Active capacity alerts')
        s=s.replace('No active demo overload warnings.','No active capacity warnings.')
        s=s.replace('Synthetic scenario status via the capstone monitoring API; not hardware SNMP alerts.', 'Scenario telemetry · rule-based assessment; not hardware measurements.')
        # Explainable AI-style insights, no misleading ML claims
        needle='          <div style={{ fontSize: 11, color: \'var(--gray-600)\', marginTop: 6 }}>'
        if s.count(needle)!=1: raise RuntimeError('Right sidebar insight anchor missing')
        block='''          {demo.insight && <div style={{ padding: 12, marginTop: 12, border: '1px solid var(--gray-300)', borderRadius: 9, background: 'var(--gray-50)' }}>
            <strong style={{fontSize:12}}>Incident Intelligence · {demo.insight.title}</strong>
            <div style={{ fontSize: 12, marginTop: 6 }}>{demo.insight.evidence}</div>
            <div style={{ fontSize: 12, marginTop: 7 }}><b>Recommended action:</b> {demo.insight.recommendation}</div>
            <div style={{ fontSize: 10, opacity: .7, marginTop: 7 }}>{demo.insight.method}</div>
          </div>}
'''
        s=s.replace(needle,block+needle,1)
        s=s.replace('telemetry_source?: string } | null>', 'telemetry_source?: string; insight?: { title: string; evidence: string; recommendation: string; method: string } } | null>')
        s=s.replace("'No active demo overload warnings.'","'No active capacity warnings.'")
        page.write_text(s)
    return 'V5 incident aggregation and incident intelligence installed.'

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--repo',type=Path,default=Path.home()/'Documents/capstone')
    args=p.parse_args();print(install(args.repo,Path(__file__).parent))
