import type { InputHTMLAttributes } from 'react'
import { Check } from '@phosphor-icons/react'
import styles from './Checkbox.module.css'

export type CheckboxProps = Omit<InputHTMLAttributes<HTMLInputElement>, 'type' | 'checked' | 'onChange'> & {
  checked: boolean
  onChange: (checked: boolean) => void
  label?: string
}

export function Checkbox({ checked, onChange, label, className, ...props }: CheckboxProps) {
  return (
    <label className={[styles.label, className].filter(Boolean).join(' ')}>
      <span className={styles.control}>
        <input {...props} className={styles.input} type="checkbox" checked={checked} onChange={event => onChange(event.target.checked)} />
        <span className={styles.box} aria-hidden="true">
          {checked && <Check size={10} weight="bold" />}
        </span>
      </span>
      {label && <span>{label}</span>}
    </label>
  )
}

export default Checkbox
