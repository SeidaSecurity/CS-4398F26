import { forwardRef } from 'react'
import type { TextareaHTMLAttributes } from 'react'
import styles from './TextArea.module.css'

export type TextAreaProps = TextareaHTMLAttributes<HTMLTextAreaElement>

export const TextArea = forwardRef<HTMLTextAreaElement, TextAreaProps>(function TextArea(
  { className, ...props },
  ref,
) {
  return <textarea ref={ref} className={[styles.textarea, className].filter(Boolean).join(' ')} {...props} />
})

export default TextArea
