/** Only persisted backend records are counted. No sample charts or fabricated values. */
import type { AuditRecord, Device, LogRecord, MetricPoint } from '../api/types'

export type NetworkEvent = {
  id: string
  timestamp: string
  source: string
  message: string
  type: 'syslog' | 'audit'
  severity: number | null
  outcome?: string
}

export type ActivityReport = {
  events: NetworkEvent[]
  syslog: MetricPoint[]
  audit: MetricPoint[]
  syslogCount: number
  auditCount: number
  errors: number
  warnings: number
  errorSeries: MetricPoint[]
  warningSeries: MetricPoint[]
  maximum: number
  severityMaximum: number
}

/** 48 evenly spaced, zero-filled buckets make gaps in actual activity visible. */
export function networkActivity(
  logs: LogRecord[],
  audits: AuditRecord[],
  windowEndMs: number,
  durationMs: number,
  device?: Device,
): ActivityReport {
  const start = windowEndMs - durationMs
  const interval = durationMs / 48
  const sources = device
    ? new Set([device.name.toLowerCase(), device.management_ip.toLowerCase()])
    : null
  const events: NetworkEvent[] = []
  const syslog = Array.from({ length: 48 }, (_, i) => ({
    t: new Date(start + i * interval).toISOString(), value: 0,
  }))
  const audit = syslog.map(point => ({ ...point }))
  let errors = 0
  let warnings = 0
  const errorSeries = syslog.map(point => ({ ...point }))
  const warningSeries = syslog.map(point => ({ ...point }))

  function bucket(timestamp: string): number | null {
    const t = Date.parse(timestamp)
    if (!Number.isFinite(t) || t < start || t > windowEndMs) return null
    return Math.min(47, Math.floor((t - start) / interval))
  }

  for (const log of logs) {
    if (sources && !sources.has(log.source.toLowerCase())) continue
    const index = bucket(log.timestamp)
    if (index === null) continue
    syslog[index].value += 1
    if (log.severity !== null && log.severity <= 3) {
      errors += 1
      errorSeries[index].value += 1
    }
    if (log.severity === 4) {
      warnings += 1
      warningSeries[index].value += 1
    }
    events.push({
      id: `syslog-${log.id}`, timestamp: log.timestamp, type: 'syslog',
      source: log.source, message: log.body, severity: log.severity,
    })
  }
  for (const item of audits) {
    // Only configuration actions are network-device activities; login/logout is not.
    if (!item.action.startsWith('configuration.')) continue
    if (sources && (!item.device_name || !sources.has(item.device_name.toLowerCase()))) continue
    const index = bucket(item.occurred_at)
    if (index === null) continue
    audit[index].value += 1
    events.push({
      id: `audit-${item.id}`, timestamp: item.occurred_at, type: 'audit',
      source: item.device_name || item.actor,
      message: `${item.action.replace('configuration.', 'Configuration ')} — ${item.outcome}${item.detail ? `: ${item.detail}` : ''}`,
      severity: null, outcome: item.outcome,
    })
  }
  events.sort((a, b) => Date.parse(b.timestamp) - Date.parse(a.timestamp))
  return {
    events, syslog, audit,
    syslogCount: syslog.reduce((n, point) => n + point.value, 0),
    auditCount: audit.reduce((n, point) => n + point.value, 0),
    errors, warnings, errorSeries, warningSeries,
    severityMaximum: Math.max(1, ...errorSeries.map((point, i) => point.value + warningSeries[i].value)),
    maximum: Math.max(1, ...syslog.map((point, i) => point.value + audit[i].value)),
  }
}
