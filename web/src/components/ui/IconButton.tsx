import { forwardRef } from 'react'
import type { ButtonHTMLAttributes } from 'react'
import type { Icon } from '@phosphor-icons/react'
import styles from './IconButton.module.css'

export type IconButtonProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'children'> & {
  icon: Icon
  label: string
  size?: 'default' | 'small'
}

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { icon: Icon, label, size = 'default', className, type = 'button', ...props },
  ref,
) {
  return (
    <button ref={ref} type={type} className={[styles.button, size === 'small' && styles.small, className].filter(Boolean).join(' ')} {...props} aria-label={label}>
      <Icon size={14} weight="regular" aria-hidden="true" />
    </button>
  )
})

export default IconButton
