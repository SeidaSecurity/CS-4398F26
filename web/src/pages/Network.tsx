import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ArrowsClockwise, Check, Clock, Cpu, DownloadSimple, HardDrives, Info, Play, Warning, X } from '@phosphor-icons/react'
import { api, useApi } from '../api'
import type { TimeWindow } from '../api'
import { RightPanel } from '../components/Layout'
import { Button, ChartSection, FilterBar, IconButton, PanelSection, Pill, Select, StatRow, TimeSeries, ToolCard } from '../components/ui'
import { formatBps, relativeTime, windowLabels } from '../lib/format'

const brand = 'var(--brand-600)'
const green = 'var(--green-600)'
const percent = (n: number) => `${Number(n.toFixed(1))}%`

function niceMaximum(max: number): number {
  if (max <= 0) return 1
  const magnitude = 10 ** Math.floor(Math.log10(max))
  const step = [1, 2, 5, 10].find(value => value * magnitude >= max) ?? 10
  return step * magnitude
}

export default function Network() {
  const [searchParams, setSearchParams] = useSearchParams()
  const scope = searchParams.get('device') ?? 'all'
  const setScope = (value: string) => setSearchParams(params => {
    const next = new URLSearchParams(params)
    if (value === 'all') next.delete('device')
    else next.set('device', value)
    return next
  })
  const [window, setWindow] = useState<TimeWindow>('24h')
  const [backupDevice, setBackupDevice] = useState('')
  const [running, setRunning] = useState(false)
  const [backupResult, setBackupResult] = useState<{ success: boolean; message: string } | null>(null)

  const devicesQuery = useApi(() => api.listDevices(), [])
  const statusesQuery = useApi(() => api.listDeviceStatus(), [])
  const alertsQuery = useApi(() => api.listAlerts(), [])
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
  const reload = useCallback(() => {
    reloadDevices()
    reloadStatuses()
    reloadAlerts()
    reloadMetrics()
  }, [reloadDevices, reloadStatuses, reloadAlerts, reloadMetrics])

  useEffect(() => {
    const interval = setInterval(reload, 60_000)
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
  const error = devicesQuery.error ?? statusesQuery.error ?? alertsQuery.error ?? metricsQuery.error
  const report = metricsQuery.data
  const metrics = report?.metrics
  const xLabels = windowLabels(report?.window ?? window)
  const throughputMax = niceMaximum([
    ...(metrics?.throughput_in_bps ?? []), ...(metrics?.throughput_out_bps ?? []),
  ].reduce((max, point) => Math.max(max, point.value), 0))
  const cpu = report?.kind === 'all' ? report.metrics.cpu_avg : report?.metrics.cpu
  const averageCpu = (report?.kind === 'all' ? report.metrics.cpu_avg : report?.networkMetrics.cpu_avg)?.at(-1)?.value

  async function runBackup() {
    if (running || !selectedBackup) return
    setRunning(true)
    setBackupResult(null)
    try {
      const result = await api.retrieveConfig(Number(selectedBackup), 'operator')
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
        <Select icon={Clock} aria-label="Time window" value={window} onChange={value => setWindow(value as TimeWindow)} options={[
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
        <ChartSection title="CPU" legend={[{ label: report?.kind === 'device' ? 'CPU' : 'Average CPU', color: brand }]} yTicks={['100%', '50%', '0%']} xLabels={xLabels}>
          <TimeSeries series={[{ data: cpu ?? [], color: brand, type: 'monotone', fill: true }]} domain={[0, 100]} formatValue={percent} />
        </ChartSection>
        {report?.kind === 'device' && (
          <ChartSection title="Memory" legend={[{ label: 'Memory', color: brand }]} yTicks={['100%', '50%', '0%']} xLabels={xLabels}>
            <TimeSeries series={[{ data: report.metrics.memory, color: brand, type: 'monotone', fill: true }]} domain={[0, 100]} formatValue={percent} />
          </ChartSection>
        )}
        <ChartSection title="Throughput" legend={[{ label: 'In rate', color: brand }, { label: 'Out rate', color: green, dashed: true }]} yTicks={[throughputMax, throughputMax / 2, 0].map(formatBps)} xLabels={xLabels}>
          <TimeSeries series={[
            { data: metrics?.throughput_in_bps ?? [], color: brand, type: 'monotone', fill: true },
            { data: metrics?.throughput_out_bps ?? [], color: green, type: 'monotone' },
          ]} domain={[0, throughputMax]} formatValue={formatBps} />
        </ChartSection>
      </div>
      <RightPanel>
        <PanelSection title="Stats" icon={Info}>
          {devicesQuery.data && statusesQuery.data && <StatRow caption="Devices up" value={<Pill tone={anyDown ? 'amber' : 'green'} icon={HardDrives}>{up}/{devices.length}</Pill>} />}
          {alertsQuery.data && <StatRow caption="Active alerts" value={<Pill tone={alerts.length ? 'red' : 'green'} icon={alerts.length ? Warning : Check}>{alerts.length}</Pill>} />}
          {lastPoll && <StatRow caption="Last poll" value={<Pill tone="gray" icon={Clock}>{relativeTime(lastPoll)}</Pill>} />}
          {averageCpu !== undefined && <StatRow caption="Average CPU" value={<Pill tone={averageCpu < 70 ? 'green' : averageCpu < 90 ? 'amber' : 'red'} icon={Cpu}>{percent(averageCpu)}</Pill>} />}
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
        <PanelSection title="Config backup" icon={DownloadSimple}>
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
        </PanelSection>
      </RightPanel>
    </>
  )
}
