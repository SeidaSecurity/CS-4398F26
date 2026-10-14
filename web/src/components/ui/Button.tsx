import { forwardRef } from 'react'
import type { ButtonHTMLAttributes } from 'react'
import type { Icon } from '@phosphor-icons/react'
import styles from './Button.module.css'

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  icon?: Icon
  variant?: 'default' | 'primary'
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { icon: Icon, variant = 'default', className, children, type = 'button', ...props },
  ref,
) {
  return (
    <button ref={ref} type={type} className={[styles.button, styles[variant], className].filter(Boolean).join(' ')} {...props}>
      {Icon && <Icon size={12} weight="regular" aria-hidden="true" />}
      {children}
    </button>
  )
})

export default Button
