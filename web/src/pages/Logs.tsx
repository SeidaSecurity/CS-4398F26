import { useCallback, useEffect, useMemo, useState } from 'react'
import { ArrowsClockwise, Article, Check, Clock, HardDrives, Info, Warning, X } from '@phosphor-icons/react'
import { api, useApi } from '../api'
import type { TimeWindow } from '../api'
import { RightPanel } from '../components/Layout'
import { ChartSection, DataTable, FilterBar, IconButton, PanelSection, Pill, Select, StatRow, TextInput, TimeSeries } from '../components/ui'
import { formatTime, windowLabels } from '../lib/format'
import { severityNames, severityPill } from '../lib/severity'
import styles from './Logs.module.css'

const windowDurations: Record<TimeWindow, number> = { '1h': 3_600_000, '24h': 86_400_000, '7d': 604_800_000 }
const brand = 'var(--brand-600)'
const red = 'var(--red-600)'

export default function Logs() {
  const [query, setQuery] = useState('')
  const [debouncedQuery, setDebouncedQuery] = useState('')
  const [source, setSource] = useState('')
  const [severity, setSeverity] = useState<number | ''>('')
  const [window, setWindow] = useState<TimeWindow>('24h')
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [now, setNow] = useState(Date.now)

  useEffect(() => {
    const timeout = setTimeout(() => setDebouncedQuery(query), 250)
    return () => clearTimeout(timeout)
  }, [query])

  const duration = windowDurations[window]
  const start = now - duration
  const since = new Date(start).toISOString()
  const sourcesQuery = useApi(() => api.searchLogs({ since, limit: 1000 }), [since])
  const logsQuery = useApi(() => api.searchLogs({
    query: debouncedQuery,
    source,
    severity: severity === '' ? undefined : severity,
    since,
    limit: 1000,
  }), [debouncedQuery, source, severity, since])

  const { reload: reloadSources } = sourcesQuery
  const { reload: reloadLogs } = logsQuery
  const reload = useCallback(() => {
    setNow(Date.now())
    reloadSources()
    reloadLogs()
  }, [reloadSources, reloadLogs])

  const logs = logsQuery.data ?? []
  const sourceOptions = [...new Set((sourcesQuery.data ?? []).map(log => log.source))]
    .sort((a, b) => a.localeCompare(b))
    .map(value => ({ value, label: value }))
  const selected = logs.find(log => log.id === selectedId)
  const errors = logs.filter(log => log.severity !== null && log.severity <= 3).length
  const warnings = logs.filter(log => log.severity === 4).length
  const sourceCounts = new Map<string, number>()
  for (const log of logs) sourceCounts.set(log.source, (sourceCounts.get(log.source) ?? 0) + 1)
  const topSource = [...sourceCounts].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))[0]?.[0] ?? '—'
  const error = sourcesQuery.error ?? logsQuery.error

  const buckets = useMemo(() => {
    const all = Array.from({ length: 48 }, (_, index) => ({
      t: new Date(start + index * duration / 48).toISOString(), value: 0,
    }))
    const errors = all.map(point => ({ ...point }))
    for (const log of logsQuery.data ?? []) {
      const timestamp = Date.parse(log.timestamp)
      if (!Number.isFinite(timestamp) || timestamp < start || timestamp > now) continue
      const index = Math.min(47, Math.floor((timestamp - start) / (duration / 48)))
      all[index].value += 1
      if (log.severity !== null && log.severity <= 3) errors[index].value += 1
    }
    return { all, errors, max: Math.max(...all.map(point => point.value)) }
  }, [logsQuery.data, start, duration, now])

  return (
    <>
      <FilterBar>
        <TextInput aria-label="Search" placeholder="Search" style={{ width: 180 }} value={query} onChange={event => setQuery(event.target.value)} />
        <Select icon={HardDrives} aria-label="Source" value={source} onChange={setSource} options={[{ value: '', label: 'All sources' }, ...sourceOptions]} />
        <Select icon={Warning} aria-label="Severity" value={String(severity)} onChange={value => setSeverity(value === '' ? '' : Number(value))} options={[
          { value: '', label: 'All severities' },
          ...severityNames.map((name, index) => ({ value: String(index), label: `${index} ${name}` })),
        ]} />
        <Select icon={Clock} aria-label="Time window" value={window} onChange={value => { setWindow(value as TimeWindow); setNow(Date.now()) }} options={[
          { value: '1h', label: 'Last hour' },
          { value: '24h', label: 'Last 24 hours' },
          { value: '7d', label: 'Last 7 days' },
        ]} />
        <IconButton size="small" icon={ArrowsClockwise} label="Refresh" onClick={reload} />
      </FilterBar>
      {error && <div role="alert" className={styles.error}>{error.message}</div>}
      <div className={styles.content}>
        <ChartSection title="Messages" legend={[{ label: 'All', color: brand }, { label: 'Errors', color: red, dashed: true }]} yTicks={[buckets.max, Math.round(buckets.max / 2), 0].map(String)} xLabels={windowLabels(window)}>
          <TimeSeries series={[
            { data: buckets.all, color: brand, type: 'step', fill: true },
            { data: buckets.errors, color: red, type: 'step' },
          ]} domain={[0, buckets.max || 1]} />
        </ChartSection>
        <DataTable className={styles.table} aria-label="Logs" rows={logs} rowKey="id" selectedKey={selectedId ?? undefined} onRowClick={log => setSelectedId(log.id)} columns={[
          { key: 'timestamp', header: 'Time', width: 140, render: (_, log) => formatTime(log.timestamp) },
          { key: 'source', header: 'Source', width: 120 },
          { key: 'severity', header: 'Severity', width: 96, render: (_, log) => severityPill(log.severity) },
          { key: 'body', header: 'Message', render: (_, log) => <span className={styles.message} title={log.body}>{log.body}</span> },
        ]} />
      </div>
      <RightPanel>
        {selected ? (
          <PanelSection title="Message" icon={Article} action={<IconButton size="small" icon={X} label="Close" onClick={() => setSelectedId(null)} />}>
            <StatRow caption="Time" value={formatTime(selected.timestamp)} />
            <StatRow caption="Received" value={formatTime(selected.received_at)} />
            <StatRow caption="Source" value={selected.source} />
            <StatRow caption="Facility" value={selected.facility ?? '—'} />
            <StatRow caption="Severity" value={severityPill(selected.severity)} />
            <StatRow caption="Parsed" value={<Pill tone={selected.parsed ? 'green' : 'gray'} icon={selected.parsed ? Check : X}>{selected.parsed ? 'Yes' : 'No'}</Pill>} />
            <div className={styles.body}>{selected.body}</div>
          </PanelSection>
        ) : (
          <PanelSection title="Stats" icon={Info}>
            <StatRow caption="Messages" value={<Pill tone="gray" icon={Article}>{logs.length}</Pill>} />
            <StatRow caption="Errors" value={<Pill tone={errors ? 'red' : 'green'} icon={errors ? X : Check}>{errors}</Pill>} />
            <StatRow caption="Warnings" value={<Pill tone={warnings ? 'amber' : 'green'} icon={warnings ? Warning : Check}>{warnings}</Pill>} />
            <StatRow caption="Top source" value={<Pill tone="gray" icon={HardDrives}>{topSource}</Pill>} />
          </PanelSection>
        )}
      </RightPanel>
    </>
  )
}
