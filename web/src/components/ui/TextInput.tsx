import { forwardRef } from 'react'
import type { InputHTMLAttributes } from 'react'
import styles from './TextInput.module.css'

export type TextInputProps = InputHTMLAttributes<HTMLInputElement>

export const TextInput = forwardRef<HTMLInputElement, TextInputProps>(function TextInput(
  { className, type = 'text', ...props },
  ref,
) {
  return <input ref={ref} type={type} className={[styles.input, className].filter(Boolean).join(' ')} {...props} />
})

export default TextInput
