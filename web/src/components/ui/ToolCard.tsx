import type { HTMLAttributes } from 'react'
import styles from './ToolCard.module.css'

export type ToolCardProps = HTMLAttributes<HTMLDivElement> & { title: string }

export function ToolCard({ title, children, className, ...props }: ToolCardProps) {
  return (
    <div className={[styles.card, className].filter(Boolean).join(' ')} {...props}>
      <div className={styles.field}>
        <div className={styles.title}>{title}</div>
        {children}
      </div>
    </div>
  )
}

export default ToolCard
