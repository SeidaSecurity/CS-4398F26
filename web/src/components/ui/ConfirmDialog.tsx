import { useEffect, useId, useRef } from 'react'
import type { ReactNode } from 'react'
import { Button } from './Button'
import styles from './ConfirmDialog.module.css'

export type ConfirmDialogProps = {
  open: boolean
  title: string
  children?: ReactNode
  confirmLabel: string
  onConfirm: () => void
  onCancel: () => void
}

export function ConfirmDialog({ open, title, children, confirmLabel, onConfirm, onCancel }: ConfirmDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null)
  const titleId = useId()
  const bodyId = useId()

  useEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return
    if (open && !dialog.open) dialog.showModal()
    else if (!open && dialog.open) dialog.close()
  }, [open])

  return (
    <dialog
      ref={dialogRef}
      className={styles.dialog}
      aria-labelledby={titleId}
      aria-describedby={children ? bodyId : undefined}
      onCancel={event => { event.preventDefault(); onCancel() }}
      onClick={event => {
        if (event.target !== event.currentTarget) return
        const bounds = event.currentTarget.getBoundingClientRect()
        if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) onCancel()
      }}
    >
      <h2 id={titleId} className={styles.title}>{title}</h2>
      {children && <div id={bodyId} className={styles.body}>{children}</div>}
      <footer className={styles.footer}>
        <Button onClick={onCancel} autoFocus>Cancel</Button>
        <Button variant="primary" onClick={onConfirm}>{confirmLabel}</Button>
      </footer>
    </dialog>
  )
}

export default ConfirmDialog
