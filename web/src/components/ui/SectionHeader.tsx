import type { HTMLAttributes, ReactNode } from 'react'
import styles from './SectionHeader.module.css'

export type SectionHeaderProps = HTMLAttributes<HTMLElement> & {
  title: string
  titleId?: string
  chip?: ReactNode
}

export function SectionHeader({ title, titleId, chip, children, className, ...props }: SectionHeaderProps) {
  return (
    <header className={[styles.header, className].filter(Boolean).join(' ')} {...props}>
      <div className={styles.heading}>
        <h2 id={titleId} className={styles.title}>{title}</h2>
        {chip}
      </div>
      {children && <div className={styles.actions}>{children}</div>}
    </header>
  )
}

export default SectionHeader
