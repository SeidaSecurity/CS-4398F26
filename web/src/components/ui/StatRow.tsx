import type { HTMLAttributes, ReactNode } from 'react'
import styles from './StatRow.module.css'

export type StatRowProps = Omit<HTMLAttributes<HTMLDivElement>, 'children'> & {
  caption: ReactNode
  value: ReactNode
}

export function StatRow({ caption, value, className, ...props }: StatRowProps) {
  return (
    <div className={[styles.row, className].filter(Boolean).join(' ')} {...props}>
      <div className={styles.caption}><span>{caption}</span><span className={styles.fence} aria-hidden="true" /></div>
      <div className={styles.value}>{value}</div>
    </div>
  )
}

export default StatRow
