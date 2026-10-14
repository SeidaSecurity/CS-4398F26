import type { TimeWindow } from '../api'

export function relativeTime(iso: string): string {
  const seconds = Math.max(0, Math.floor((Date.now() - Date.parse(iso)) / 1000))
  if (seconds < 60) return `${seconds}s ago`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`
  return `${Math.floor(seconds / 86400)}d ago`
}

export function formatTime(iso: string): string {
  return new Intl.DateTimeFormat('en-US', {
    month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', hour12: true,
  }).format(new Date(iso))
}

export function formatBps(n: number): string {
  const units = ['bps', 'Kbps', 'Mbps', 'Gbps']
  const index = n === 0 ? 0 : Math.min(3, Math.max(0, Math.floor(Math.log10(Math.abs(n)) / 3)))
  return `${Number((n / 1000 ** index).toFixed(1))} ${units[index]}`
}

export function windowLabels(window: TimeWindow): [string, string, string] {
  switch (window) {
    case '1h': return ['60 min', '30 min', 'Now']
    case '24h': return ['24 hours', '12 hours', 'Now']
    case '7d': return ['7 days', '3.5 days', 'Now']
  }
}
