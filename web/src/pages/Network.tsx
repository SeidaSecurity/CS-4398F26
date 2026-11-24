import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ArrowsClockwise, Article, Check, Clock, Cpu, DownloadSimple, HardDrives, Info, Play, Warning, X } from '@phosphor-icons/react'
import { api, useApi } from '../api'
import type { TimeWindow } from '../api'
import { useAuth } from '../auth'
import { RightPanel } from '../components/Layout'
import { Button, ChartSection, FilterBar, IconButton, PanelSection, Pill, Select, StatRow, TimeSeries, ToolCard } from '../components/ui'
import { formatBps, relativeTime, windowLabels } from '../lib/format'
import { networkActivity } from '../lib/networkActivity'
import styles from './NetworkActivity.module.css'

const brand = 'var(--brand-600)'
const green = 'var(--green-600)'
const percent = (n: number) => `${Number(n.toFixed(1))}%`
const windowMs: Record<TimeWindow, number> = { '1h': 3_600_000, '24h': 86_400_000, '7d': 604_800_000 }
const red = 'var(--red-600)'

function niceMaximum(max: number): number {
  if (max <= 0) return 1
  const magnitude = 10 ** Math.floor(Math.log10(max))
  const step = [1, 2, 5, 10].find(value => value * magnitude >= max) ?? 10
  return step * magnitude
}

export default function Network() {
  const { isAdmin } = useAuth() // viewers see no write controls (R7.2)
  const [searchParams, setSearchParams] = useSearchParams()
  const scope = searchParams.get('device') ?? 'all'
  const setScope = (value: string) => setSearchParams(params => {
    const next = new URLSearchParams(params)
    if (value === 'all') next.delete('device')
    else next.set('device', value)
    return next
  })
  const [window, setWindow] = useState<TimeWindow>('1h')
  const [activityNow, setActivityNow] = useState(Date.now)
  // CS4398_DEMO_WARNINGS_PANEL: opt-in, API-only status from isolated localhost simulator.
  const [demo, setDemo] = useState<{ running: boolean; standby_enabled?: boolean; active_warnings: Array<{ source: string; severity: string; message: string }>; telemetry_source?: string; insight?: { title: string; evidence: string; recommendation: string; method: string } } | null>(null)
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

  const logSince = new Date(activityNow - windowMs[window]).toISOString()
  const [backupDevice, setBackupDevice] = useState('')
  const [running, setRunning] = useState(false)
  const [backupResult, setBackupResult] = useState<{ success: boolean; message: string } | null>(null)

  const devicesQuery = useApi(() => api.listDevices(), [])
  // CS4398_INCIDENT_FEED_V5 — read-only aggregation of persisted backend syslog.
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
  const statusesQuery = useApi(() => api.listDeviceStatus(), [])
  const alertsQuery = useApi(() => api.listAlerts(), [])
  const logsQuery = useApi(() => api.searchLogs({ since: logSince, limit: 1000 }), [logSince])
  const auditsQuery = useApi(() => api.listAudit(), [])
  const metricsQuery = useApi(async () => {
    if (scope === 'all') return { kind: 'all' as const, window, metrics: await api.getNetworkMetrics(window) }
    const [metrics, networkMetrics] = await Promise.all([
      api.getDeviceMetrics(Number(scope), window),
      api.getNetworkMetrics(window),
    ])
    return { kind: 'device' as const, window, metrics, networkMetrics }
  }, [scope, window])

  const { reload: reloadDevices } = devicesQuery
  const { reload: reloadStatuses } = statusesQuery
  const { reload: reloadAlerts } = alertsQuery
  const { reload: reloadMetrics } = metricsQuery
  const { reload: reloadAudit } = auditsQuery
  const reload = useCallback(() => {
    reloadDevices()
    reloadStatuses()
    reloadAlerts()
    reloadMetrics()
    reloadAudit()
    setActivityNow(Date.now()) // logSince changes, reloading recent syslog from the backend
  }, [reloadDevices, reloadStatuses, reloadAlerts, reloadMetrics, reloadAudit])

  useEffect(() => {
    const interval = setInterval(reload, 3_000)
    return () => clearInterval(interval)
  }, [reload])

  const devices = devicesQuery.data ?? []
  const statuses = statusesQuery.data ?? []
  const alerts = alertsQuery.data ?? []
  const statusesByDevice = new Map(statuses.map(status => [status.device_id, status]))
  const deviceNames = new Map(devices.map(device => [device.id, device.name]))
  const deviceOptions = devices.map(device => ({ value: String(device.id), label: device.name }))
  const selectedBackup = backupDevice || deviceOptions[0]?.value || ''
  const up = devices.filter(device => statusesByDevice.get(device.id)?.state === 'up').length
  const anyDown = devices.some(device => statusesByDevice.get(device.id)?.state === 'down')
  const lastPoll = statuses.reduce<string | undefined>((latest, status) =>
    !latest || Date.parse(status.last_poll_at) > Date.parse(latest) ? status.last_poll_at : latest, undefined)
  const sortedDevices = [...devices].sort((a, b) =>
    Number(statusesByDevice.get(b.id)?.state === 'down') - Number(statusesByDevice.get(a.id)?.state === 'down')
    || a.name.localeCompare(b.name))
  const error = devicesQuery.error ?? statusesQuery.error ?? alertsQuery.error ?? metricsQuery.error ?? logsQuery.error ?? auditsQuery.error
  const report = metricsQuery.data
  const metrics = report?.metrics
  const xLabels = windowLabels(report?.window ?? window)
  const throughputMax = niceMaximum([
    ...(metrics?.throughput_in_bps ?? []), ...(metrics?.throughput_out_bps ?? []),
  ].reduce((max, point) => Math.max(max, point.value), 0))
  const cpu = report?.kind === 'all' ? report.metrics.cpu_avg : report?.metrics.cpu
  const averageCpu = (report?.kind === 'all' ? report.metrics.cpu_avg : report?.networkMetrics.cpu_avg)?.at(-1)?.value
  const selectedDevice = devices.find(device => String(device.id) === scope)
  const activity = networkActivity(logsQuery.data ?? [], auditsQuery.data ?? [], activityNow, windowMs[window], selectedDevice)
  // CS4398_LIVE_INCIDENT_TIMELINE: persisted syslog, 2.5-second buckets.
  const liveActivity = networkActivity(logsQuery.data ?? [], auditsQuery.data ?? [], activityNow, 120_000, selectedDevice)
  const incidentBuckets = incidentFeed?.buckets ?? []
  const incidentPoints = (key: 'all' | 'warnings' | 'errors') => incidentBuckets.map(b => ({t:b.t,value:b[key]}))
  const incidentMax = Math.max(1, ...incidentBuckets.map(b => b.all))
  const incidentSeverityMax = Math.max(1, ...incidentBuckets.map(b => b.errors + b.warnings))
  const memory = report?.kind === 'device' ? report.metrics.memory : []
  const hasThroughput = Boolean(metrics?.throughput_in_bps.length || metrics?.throughput_out_bps.length)
  const hasSnmpMetrics = Boolean(cpu?.length || memory.length || hasThroughput)

  async function runBackup() {
    if (running || !selectedBackup) return
    setRunning(true)
    setBackupResult(null)
    try {
      const result = await api.retrieveConfig(Number(selectedBackup))
      setBackupResult({ success: true, message: `Saved version ${result.version}` })
    } catch (reason) {
      setBackupResult({ success: false, message: reason instanceof Error ? reason.message : String(reason) })
    } finally {
      setRunning(false)
    }
  }

  return (
    <>
      <FilterBar>
        <Select icon={HardDrives} aria-label="Device scope" value={scope} onChange={setScope} options={[{ value: 'all', label: 'All devices' }, ...deviceOptions]} />
        <Select icon={Clock} aria-label="Time window" value={window} onChange={value => { setWindow(value as TimeWindow); setActivityNow(Date.now()) }} options={[
          { value: '1h', label: 'Last hour' },
          { value: '24h', label: 'Last 24 hours' },
          { value: '7d', label: 'Last 7 days' },
        ]} />
        <IconButton size="small" icon={ArrowsClockwise} label="Refresh" onClick={reload} />
      </FilterBar>
      {error && <div role="alert" style={{ padding: '0 16px', fontSize: 12, color: 'var(--red-800)' }}>{error.message}</div>}
      <div style={{ display: 'flex', flexDirection: 'column', padding: '12px 0', gap: 16 }}>
        {report?.kind === 'all' && (
          <ChartSection title="Devices up" chip={<Pill tone="gray" icon={HardDrives}>{devices.length} devices</Pill>} legend={[{ label: 'Up count', color: brand }]} yTicks={[devices.length, Math.round(devices.length / 2), 0].map(String)} xLabels={xLabels}>
            <TimeSeries series={[{ data: report.metrics.devices_up, color: brand, type: 'step' }]} domain={[0, devices.length]} />
          </ChartSection>
        )}
        {Boolean(cpu?.length) && <ChartSection title="CPU" legend={[{ label: report?.kind === 'device' ? 'CPU' : 'Average CPU', color: brand }]} yTicks={['100%', '50%', '0%']} xLabels={xLabels}>
          <TimeSeries series={[{ data: cpu ?? [], color: brand, type: 'monotone', fill: true }]} domain={[0, 100]} formatValue={percent} />
        </ChartSection>}
        {report?.kind === 'device' && memory.length > 0 && (
          <ChartSection title="Memory" legend={[{ label: 'Memory', color: brand }]} yTicks={['100%', '50%', '0%']} xLabels={xLabels}>
            <TimeSeries series={[{ data: report.metrics.memory, color: brand, type: 'monotone', fill: true }]} domain={[0, 100]} formatValue={percent} />
          </ChartSection>
        )}
        {hasThroughput && <ChartSection title="Throughput" legend={[{ label: 'In rate', color: brand }, { label: 'Out rate', color: green, dashed: true }]} yTicks={[throughputMax, throughputMax / 2, 0].map(formatBps)} xLabels={xLabels}>
          <TimeSeries series={[
            { data: metrics?.throughput_in_bps ?? [], color: brand, type: 'monotone', fill: true },
            { data: metrics?.throughput_out_bps ?? [], color: green, type: 'monotone' },
          ]} domain={[0, throughputMax]} formatValue={formatBps} />
        </ChartSection>}
        {!hasSnmpMetrics && (
          <div className={styles.notice} role="status">
            <strong>CPU, memory and throughput are unavailable.</strong> This SSH-only virtual router does not expose SNMP counters. The activity chart below uses real stored syslog and configuration-audit events, not invented utilization data.
          </div>
        )}
        {demo && <>
          <ChartSection title="Live network activity (last 2 minutes)" chip={<Pill tone="gray" icon={Article}>{incidentFeed?.total ?? liveActivity.syslogCount + liveActivity.auditCount} events</Pill>} legend={[{ label: 'Syslog', color: brand }, { label: 'Config changes', color: green, dashed: true }]} yTicks={[incidentFeed ? incidentMax : liveActivity.maximum, Math.round((incidentFeed ? incidentMax : liveActivity.maximum) / 2), 0].map(String)} xLabels={['-120s', '-90s', '-60s', '-30s', 'now']}>
            <TimeSeries series={[{ data: incidentFeed ? incidentPoints('all') : liveActivity.syslog, color: brand, type: 'step', fill: true }, { data: liveActivity.audit, color: green, type: 'step', dashed: true }]} domain={[0, incidentFeed ? incidentMax : liveActivity.maximum]} />
          </ChartSection>
          <ChartSection title="Live warnings / errors (last 2 minutes)" legend={[{ label: 'Errors', color: red }, { label: 'Warnings', color: 'var(--amber-800)', dashed: true }]} yTicks={[incidentFeed ? incidentSeverityMax : liveActivity.severityMaximum, Math.round((incidentFeed ? incidentSeverityMax : liveActivity.severityMaximum) / 2), 0].map(String)} xLabels={['-120s', '-90s', '-60s', '-30s', 'now']}>
            <TimeSeries series={[{ data: incidentFeed ? incidentPoints('errors') : liveActivity.errorSeries, color: red, type: 'step', fill: true }, { data: incidentFeed ? incidentPoints('warnings') : liveActivity.warningSeries, color: 'var(--amber-800)', type: 'step', dashed: true }]} domain={[0, incidentFeed ? incidentSeverityMax : liveActivity.severityMaximum]} />
          </ChartSection>
        </>}
        <ChartSection title="Network activity" chip={<Pill tone="gray" icon={Article}>{incidentFeed ? incidentFeed.total : activity.syslogCount + activity.auditCount} events</Pill>} legend={[{ label: 'Syslog', color: brand }, { label: 'Config changes', color: green, dashed: true }]} yTicks={[incidentFeed ? incidentMax : activity.maximum, Math.round((incidentFeed ? incidentMax : activity.maximum) / 2), 0].map(String)} xLabels={incidentFeed ? ["-120s", "-90s", "-60s", "-30s", "now"] : xLabels}>
          <TimeSeries series={[
            { data: incidentFeed ? incidentPoints('all') : activity.syslog, color: brand, type: 'step', fill: true },
            { data: activity.audit, color: green, type: 'step', dashed: true },
          ]} domain={[0, incidentFeed ? incidentMax : activity.maximum]} />
        </ChartSection>
        <ChartSection title="Log severity" legend={[{ label: 'Errors (0–3)', color: red }, { label: 'Warnings (4)', color: 'var(--amber-800)', dashed: true }]} yTicks={[incidentFeed ? incidentSeverityMax : activity.severityMaximum, Math.round((incidentFeed ? incidentSeverityMax : activity.severityMaximum) / 2), 0].map(String)} xLabels={incidentFeed ? ["-120s", "-90s", "-60s", "-30s", "now"] : xLabels}>
          <TimeSeries series={[
            { data: incidentFeed ? incidentPoints('errors') : activity.errorSeries, color: red, type: 'step', fill: true },
            { data: incidentFeed ? incidentPoints('warnings') : activity.warningSeries, color: 'var(--amber-800)', type: 'step', dashed: true },
          ]} domain={[0, incidentFeed ? incidentSeverityMax : activity.severityMaximum]} />
        </ChartSection>
        <div className={styles.caption}>Graphs use stored syslog and device configuration audit records, not generated utilization data. Recent individual messages are capped; the incident charts aggregate all stored events for the last two minutes. For a 127.0.0.1 device, ICMP availability only proves your Mac responds to ping.</div>
      </div>
      <RightPanel>
        {demo && <PanelSection title="Active capacity alerts" icon={Warning}>
          {demo.active_warnings.length ? demo.active_warnings.map((item, i) => (
            <div key={i} role="alert" style={{ marginBottom: 8, borderRadius: 8, padding: '10px 12px', background: '#fff2df', border: '1px solid #e1a052', color: '#713d07', fontSize: 12 }}>
              <strong>{item.severity.toUpperCase()} — {item.source}</strong>
              <div style={{ marginTop: 4 }}>{item.message}</div>
            </div>
          )) : <div role="status" style={{ padding: 8, fontSize: 12, color: 'var(--green-800)' }}>
            {demo.standby_enabled && demo.running ? 'Standby enabled — overload resolved automatically.' : 'No active capacity warnings.'}
          </div>}
          {demo.insight && <div style={{ padding: 12, marginTop: 12, border: '1px solid var(--gray-300)', borderRadius: 9, background: 'var(--gray-50)' }}>
            <strong style={{fontSize:12}}>Incident Intelligence · {demo.insight.title}</strong>
            <div style={{ fontSize: 12, marginTop: 6 }}>{demo.insight.evidence}</div>
            <div style={{ fontSize: 12, marginTop: 7 }}><b>Recommended action:</b> {demo.insight.recommendation}</div>
            <div style={{ fontSize: 10, opacity: .7, marginTop: 7 }}>{demo.insight.method}</div>
          </div>}
          <div style={{ fontSize: 11, color: 'var(--gray-600)', marginTop: 6 }}>
            Scenario telemetry · rule-based assessment; not hardware measurements.
          </div>
        </PanelSection>}

        <PanelSection title="Stats" icon={Info}>
          {devicesQuery.data && statusesQuery.data && <StatRow caption="Devices up" value={<Pill tone={anyDown ? 'amber' : 'green'} icon={HardDrives}>{up}/{devices.length}</Pill>} />}
          {alertsQuery.data && <StatRow caption="Active alerts" value={<Pill tone={alerts.length ? 'red' : 'green'} icon={alerts.length ? Warning : Check}>{alerts.length}</Pill>} />}
          {lastPoll && <StatRow caption="Last poll" value={<Pill tone="gray" icon={Clock}>{relativeTime(lastPoll)}</Pill>} />}
          {averageCpu !== undefined && <StatRow caption="Average CPU" value={<Pill tone={averageCpu < 70 ? 'green' : averageCpu < 90 ? 'amber' : 'red'} icon={Cpu}>{percent(averageCpu)}</Pill>} />}
        </PanelSection>
        <PanelSection title="Activity" icon={Article}>
          <StatRow caption="Syslog messages" value={<Pill tone="gray" icon={Article}>{activity.syslogCount}</Pill>} />
          <StatRow caption="Config actions" value={<Pill tone="gray" icon={Check}>{activity.auditCount}</Pill>} />
          <StatRow caption="Error-level logs" value={<Pill tone={activity.errors ? "red" : "green"} icon={activity.errors ? Warning : Check}>{activity.errors}</Pill>} />
          <StatRow caption="Warnings" value={<Pill tone={activity.warnings ? "amber" : "green"} icon={activity.warnings ? Warning : Check}>{activity.warnings}</Pill>} />
        </PanelSection>
        <PanelSection title="Recent network events" icon={Article}>
          {activity.events.length ? (
            <div className={styles.eventList}>
              {activity.events.slice(0, 8).map(event => (
                <div className={styles.event} key={event.id}>
                  <div className={styles.eventHeader}>
                    <span className={styles.eventSource}>{event.source} · {event.type === "syslog" ? "Syslog" : "Audit"}</span>
                    <span className={styles.eventTime} title={event.timestamp}>{relativeTime(event.timestamp)}</span>
                  </div>
                  <div className={styles.eventBody}>{event.message}</div>
                </div>
              ))}
            </div>
          ) : <span className={styles.empty}>No events in this time window. Try retrieving or pushing a configuration; with syslog enabled, SSH activity will also appear.</span>}
        </PanelSection>
        <PanelSection title="Devices" icon={HardDrives}>
          {sortedDevices.map(device => {
            const status = statusesByDevice.get(device.id)
            if (!status) return null
            const selected = scope === String(device.id)
            return (
              <button key={device.id} type="button" aria-pressed={selected} onClick={() => setScope(String(device.id))} style={{ appearance: 'none', border: 0, padding: 0, margin: 0, background: 'transparent', font: 'inherit', textAlign: 'left', width: '100%', cursor: 'pointer', color: selected ? 'var(--brand-800)' : 'inherit' }}>
                <StatRow title={'Last poll ' + relativeTime(status.last_poll_at)} caption={<span style={{ color: selected ? 'var(--brand-800)' : undefined }}>{device.name}</span>} value={
                  <Pill tone={status.state === 'up' ? 'green' : 'red'} icon={status.state === 'up' ? Check : X}>{status.state === 'up' ? 'Up' : 'Down'}</Pill>
                } />
              </button>
            )
          })}
        </PanelSection>
        {alerts.length > 0 && <PanelSection title="Alerts" icon={Warning}>
          {alerts.map(alert => (
            <div key={alert.id} style={{ display: 'flex', flexDirection: 'column', gap: 2, background: '#ffe8e8', boxShadow: '0 0 0 1px #ffc7c7', borderRadius: 8, padding: '6px 10px', fontSize: 12, lineHeight: '16px', color: 'var(--red-800)' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontWeight: 500 }}>{deviceNames.get(alert.device_id)}</span>
                <span style={{ marginLeft: 'auto', textAlign: 'right', whiteSpace: 'nowrap', opacity: 0.7 }}>{relativeTime(alert.raised_at)}</span>
              </div>
              <span>{alert.message}</span>
            </div>
          ))}
        </PanelSection>}
        {isAdmin && <PanelSection title="Config backup" icon={DownloadSimple}>
          <div style={{ fontSize: 12, lineHeight: '16px', color: 'var(--gray-600)' }}>Save a device's running configuration as a new version.</div>
          <ToolCard title="Run a backup">
            <div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: 6 }}>
                <Select style={{ width: '100%' }} aria-label="Backup device" value={selectedBackup} options={deviceOptions} disabled={running || !devices.length} onChange={value => { setBackupDevice(value); setBackupResult(null) }} />
                <Button style={{ background: '#fff' }} icon={Play} disabled={running || !selectedBackup} onClick={runBackup}>Run</Button>
              </div>
              {backupResult && <div role="status" style={{ marginTop: 8, padding: '4px 8px', borderRadius: 6, fontSize: 12, color: backupResult.success ? 'var(--green-800)' : 'var(--red-800)', background: backupResult.success ? 'var(--green-50)' : 'var(--red-50)' }}>{backupResult.message}</div>}
            </div>
          </ToolCard>
        </PanelSection>}
      </RightPanel>
    </>
  )
}
