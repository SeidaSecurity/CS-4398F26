import { useId, useMemo } from 'react'
import { Area, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { TooltipContentProps } from 'recharts'
import { formatTime } from '../../lib/format'
import styles from './TimeSeries.module.css'

export type TimeSeriesPoint = { t: string; value: number }

export type TimeSeriesSeries = {
  data: TimeSeriesPoint[]
  color: string
  type?: 'step' | 'monotone'
  dashed?: boolean
  fill?: boolean
}

export type TimeSeriesProps = {
  series: TimeSeriesSeries[]
  domain?: [number, number]
  formatValue?: (n: number) => string
}

function SeriesTooltip({ active, payload, label, formatValue }: TooltipContentProps & Pick<TimeSeriesProps, 'formatValue'>) {
  if (!active || !payload.length) return null
  return (
    <div className={styles.tooltip}>
      <div className={styles.time}>{formatTime(String(label))}</div>
      {payload.map((item, index) => (
        <div key={`${String(item.dataKey)}-${index}`} className={styles.value}>
          <span className={styles.swatch} style={{ backgroundColor: item.color }} aria-hidden="true" />
          <span>{typeof item.value === 'number' ? (formatValue?.(item.value) ?? item.value.toLocaleString()) : String(item.value ?? '')}</span>
        </div>
      ))}
    </div>
  )
}

export function TimeSeries({ series, domain, formatValue }: TimeSeriesProps) {
  const gradientId = useId()
  const data = useMemo(() => {
    const points = new Map<string, { t: string } & Record<string, string | number>>()
    series.forEach((item, index) => {
      item.data.forEach((point) => {
        let row = points.get(point.t)
        if (!row) {
          row = { t: point.t }
          points.set(point.t, row)
        }
        row[`series${index}`] = point.value
      })
    })
    return Array.from(points.values())
  }, [series])

  return (
    <div className={styles.chart}>
      <ResponsiveContainer width="100%" height={128}>
        <ComposedChart data={data} margin={{ top: 8, right: 0, bottom: 8, left: 0 }} accessibilityLayer>
          <defs>
            {series.map((item, index) => item.fill && (
              <linearGradient key={index} id={`${gradientId}-${index}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={item.color} stopOpacity={0.1} />
                <stop offset="50%" stopColor={item.color} stopOpacity={0.1} />
                <stop offset="100%" stopColor={item.color} stopOpacity={0} />
              </linearGradient>
            ))}
          </defs>
          <XAxis dataKey="t" hide padding={{ left: 0, right: 0 }} />
          <YAxis hide domain={domain ?? [0, 'auto']} allowDataOverflow={Boolean(domain)} width={0} />
          <Tooltip
            content={(props) => <SeriesTooltip {...props} formatValue={formatValue} />}
            cursor={{ stroke: 'var(--gray-200)', strokeWidth: 1 }}
            isAnimationActive={false}
          />
          {series.map((item, index) => {
            const shared = {
              dataKey: `series${index}`,
              type: item.type ?? 'monotone' as const,
              stroke: item.color,
              strokeWidth: 1.2,
              strokeLinecap: 'square' as const,
              strokeDasharray: item.dashed ? '2 2' : undefined,
              dot: false as const,
              activeDot: false as const,
              isAnimationActive: false,
            }
            return item.fill
              ? <Area key={index} {...shared} fill={`url(#${gradientId}-${index})`} fillOpacity={1} />
              : <Line key={index} {...shared} />
          })}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}

export default TimeSeries
