import { useEffect, useId, useRef, useState } from 'react'
import type { ButtonHTMLAttributes, KeyboardEvent } from 'react'
import { CaretDown, Check } from '@phosphor-icons/react'
import type { Icon } from '@phosphor-icons/react'
import { Button } from './Button'
import styles from './Select.module.css'

export type SelectOption = { value: string; label: string }

export type SelectProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'value' | 'onChange' | 'children'> & {
  value: string
  options: SelectOption[]
  onChange: (value: string) => void
  icon?: Icon
}

export function Select({ value, options, onChange, icon, className, disabled, onClick, onKeyDown, ...props }: SelectProps) {
  const [open, setOpen] = useState(false)
  const [activeIndex, setActiveIndex] = useState(0)
  const rootRef = useRef<HTMLDivElement>(null)
  const buttonRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const searchRef = useRef({ text: '', time: 0 })
  const id = useId()
  const selectedIndex = options.findIndex((option) => option.value === value)
  const active = Math.min(activeIndex, options.length - 1)
  const expanded = open && !disabled

  useEffect(() => {
    if (!expanded) return
    menuRef.current?.focus()
    const handleOutside = (event: PointerEvent) => {
      if (event.target instanceof Node && !rootRef.current?.contains(event.target)) setOpen(false)
    }
    document.addEventListener('pointerdown', handleOutside)
    return () => document.removeEventListener('pointerdown', handleOutside)
  }, [expanded])

  useEffect(() => {
    if (expanded && active >= 0) {
      document.getElementById(`${id}-option-${active}`)?.scrollIntoView({ block: 'nearest' })
    }
  }, [active, expanded, id])

  function showMenu(index = Math.max(selectedIndex, 0)) {
    searchRef.current = { text: '', time: 0 }
    setActiveIndex(index)
    setOpen(true)
  }

  function closeMenu() {
    setOpen(false)
    buttonRef.current?.focus()
  }

  function choose(index: number) {
    const option = options[index]
    closeMenu()
    if (option && option.value !== value) onChange(option.value)
  }

  function handleMenuKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const count = options.length
    if (event.key === 'Escape') {
      event.preventDefault()
      event.stopPropagation()
      closeMenu()
    } else if (event.key === 'Tab') {
      setOpen(false)
      buttonRef.current?.focus()
    } else if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      choose(active)
    } else if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
      event.preventDefault()
      if (!count) return
      if (event.key === 'Home') setActiveIndex(0)
      else if (event.key === 'End') setActiveIndex(count - 1)
      else setActiveIndex((active + (event.key === 'ArrowDown' ? 1 : -1) + count) % count)
    } else if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
      event.preventDefault()
      const now = Date.now()
      const text = (now - searchRef.current.time < 700 ? searchRef.current.text : '') + event.key.toLowerCase()
      searchRef.current = { text, time: now }
      const query = [...text].every((character) => character === text[0]) ? text[0] : text
      for (let offset = 1; offset <= count; offset += 1) {
        const index = (active + offset + count) % count
        if (options[index].label.toLowerCase().startsWith(query)) {
          setActiveIndex(index)
          break
        }
      }
    }
  }

  return (
    <div ref={rootRef} className={[styles.select, className].filter(Boolean).join(' ')}>
      <Button
        {...props}
        ref={buttonRef}
        className={styles.trigger}
        icon={icon}
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={expanded}
        aria-controls={expanded ? `${id}-menu` : undefined}
        onClick={(event) => {
          onClick?.(event)
          if (!event.defaultPrevented) {
            if (expanded) closeMenu()
            else showMenu()
          }
        }}
        onKeyDown={(event) => {
          onKeyDown?.(event)
          if (event.defaultPrevented) return
          if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            event.preventDefault()
            showMenu(selectedIndex >= 0 ? selectedIndex : event.key === 'ArrowUp' ? options.length - 1 : 0)
          } else if (event.key === 'Escape' && expanded) {
            event.preventDefault()
            closeMenu()
          }
        }}
      >
        <span>{options[selectedIndex]?.label ?? value}</span>
        <CaretDown size={10} weight="regular" aria-hidden="true" />
      </Button>
      {expanded && (
        <div
          ref={menuRef}
          id={`${id}-menu`}
          className={styles.menu}
          role="listbox"
          tabIndex={-1}
          aria-label={props['aria-label'] ?? options[selectedIndex]?.label ?? value}
          aria-activedescendant={active >= 0 ? `${id}-option-${active}` : undefined}
          onKeyDown={handleMenuKeyDown}
          onBlur={(event) => {
            if (!rootRef.current?.contains(event.relatedTarget)) setOpen(false)
          }}
        >
          {options.map((option, index) => (
            <div
              key={option.value}
              id={`${id}-option-${index}`}
              role="option"
              aria-selected={option.value === value}
              className={[styles.option, index === active ? styles.active : ''].filter(Boolean).join(' ')}
              onMouseEnter={() => setActiveIndex(index)}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => choose(index)}
            >
              <span>{option.label}</span>
              {option.value === value && <Check size={12} weight="regular" aria-hidden="true" />}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default Select
