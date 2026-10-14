import type { HTMLAttributes } from 'react'
import { Funnel } from '@phosphor-icons/react'
import styles from './FilterBar.module.css'

export type FilterBarProps = HTMLAttributes<HTMLDivElement>

export function FilterBar({ children, className, ...props }: FilterBarProps) {
  return (
    <div className={[styles.bar, className].filter(Boolean).join(' ')} {...props}>
      <span className={styles.label}><Funnel size={12} weight="regular" aria-hidden="true" />Filters</span>
      <span className={styles.fence} aria-hidden="true" />
      <div className={styles.controls}>{children}</div>
    </div>
  )
}

export default FilterBar
