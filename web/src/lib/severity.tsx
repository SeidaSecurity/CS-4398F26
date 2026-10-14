import { Warning } from '@phosphor-icons/react'
import { Pill } from '../components/ui'

export const severityNames = ['Emergency', 'Alert', 'Critical', 'Error', 'Warning', 'Notice', 'Info', 'Debug']

export function severityPill(severity: number | null) {
  const isError = severity !== null && severity >= 0 && severity <= 3
  const isWarning = severity === 4
  return <Pill size="small" tone={isError ? 'red' : isWarning ? 'amber' : 'gray'} icon={isError || isWarning ? Warning : undefined}>{severity === null ? '—' : severityNames[severity] ?? '—'}</Pill>
}
