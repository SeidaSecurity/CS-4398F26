import type { HTMLAttributes } from 'react'
import type { Icon } from '@phosphor-icons/react'
import styles from './Pill.module.css'

export type PillProps = HTMLAttributes<HTMLSpanElement> & {
  tone: 'green' | 'red' | 'amber' | 'gray'
  icon?: Icon
  size?: 'default' | 'small'
}

export function Pill({ tone, icon: Icon, size = 'default', children, className, ...props }: PillProps) {
  return (
    <span className={[styles.pill, styles[tone], size === 'small' && styles.small, className].filter(Boolean).join(' ')} {...props}>
      {Icon && <Icon size={12} weight="regular" aria-hidden="true" />}
      {children}
    </span>
  )
}

export default Pill
