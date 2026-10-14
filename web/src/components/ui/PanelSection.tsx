import { useId } from 'react'
import type { HTMLAttributes, ReactNode } from 'react'
import type { Icon } from '@phosphor-icons/react'
import styles from './PanelSection.module.css'

export type PanelSectionProps = HTMLAttributes<HTMLElement> & {
  title: string
  icon?: Icon
  action?: ReactNode
}

export function PanelSection({ title, icon: Icon, action, children, className, ...props }: PanelSectionProps) {
  const id = useId()
  return (
    <section aria-labelledby={id} className={[styles.section, className].filter(Boolean).join(' ')} {...props}>
      <header className={styles.header}>
        {Icon && <Icon size={12} weight="regular" aria-hidden="true" />}
        <h2 id={id} className={styles.title}>{title}</h2>
        {action && <div className={styles.action}>{action}</div>}
      </header>
      <div className={styles.fence} aria-hidden="true" />
      <div className={styles.content}>{children}</div>
    </section>
  )
}

export default PanelSection
