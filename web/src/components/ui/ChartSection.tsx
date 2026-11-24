import { useId } from 'react'
import type { HTMLAttributes, ReactNode } from 'react'
import { SectionHeader } from './SectionHeader'
import styles from './ChartSection.module.css'

export type ChartLegendItem = { label: string; color: string; dashed?: boolean }

export type ChartSectionProps = HTMLAttributes<HTMLElement> & {
  title: string
  chip?: ReactNode
  legend?: ChartLegendItem[]
  yTicks: string[]
  xLabels: string[]
}

export function ChartSection({ title, chip, legend, yTicks, xLabels, children, className, ...props }: ChartSectionProps) {
  const id = useId()
  return (
    <section className={[styles.section, className].filter(Boolean).join(' ')} aria-labelledby={id} {...props}>
      <SectionHeader title={title} titleId={id} chip={chip}>
        {legend && legend.length > 0 && (
          <div className={styles.legend} style={{ color: 'var(--gray-700)' }}>
            {legend.map((item, index) => (
              <span key={`${item.label}-${index}`} className={styles.legendItem}>
                <span className={styles.swatch} style={{ borderColor: item.color, borderTopStyle: item.dashed ? 'dotted' : 'solid' }} aria-hidden="true" />
                {item.label}
              </span>
            ))}
          </div>
        )}
      </SectionHeader>
      <div className={styles.report}>
        <div className={styles.yAxis}>
          {yTicks.map((tick, index) => <span key={`${tick}-${index}`}>{tick}</span>)}
        </div>
        <div className={styles.plot}>{children}</div>
      </div>
      <div className={styles.xAxis}>
        <span>{xLabels[0]}</span>
        <span className={styles.center}>{xLabels[1]}</span>
        <span className={styles.now}><span className={styles.dot} aria-hidden="true" />{xLabels[2]}</span>
      </div>
    </section>
  )
}

export default ChartSection
