import { useEffect, useRef, useState } from 'react'
import { CaretDown, MagnifyingGlass } from '@phosphor-icons/react'
import { NavLink, useNavigate } from 'react-router-dom'
import { nav } from '../nav'
import styles from './Sidebar.module.css'

export default function Sidebar() {
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({})
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [highlightedIndex, setHighlightedIndex] = useState(0)
  const dialog = useRef<HTMLDialogElement>(null)
  const navigate = useNavigate()
  const items = nav.flatMap((group) => group.items)
  const filtered = items.filter((item) =>
    item.label.toLowerCase().includes(query.trim().toLowerCase()),
  )

  useEffect(() => {
    const togglePalette = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setOpen((current) => !current)
      }
    }

    window.addEventListener('keydown', togglePalette)
    return () => window.removeEventListener('keydown', togglePalette)
  }, [])

  useEffect(() => {
    if (open) {
      setQuery('')
      setHighlightedIndex(0)
      dialog.current?.showModal()
    } else {
      dialog.current?.close()
    }
  }, [open])

  const select = (path: string) => {
    navigate(path)
    setOpen(false)
  }

  return (
    <aside className={styles.sidebar}>
      <header className={styles.header}>
        <div className={styles.identity}>
          <span className={styles.wordmark}>netmgr</span>
          <span className={styles.avatar}>OP</span>
        </div>
        <button
          className={styles.search}
          type="button"
          aria-label="Search navigation"
          aria-haspopup="dialog"
          aria-expanded={open}
          onClick={() => setOpen(true)}
        >
          <MagnifyingGlass size={12} weight="regular" aria-hidden="true" />
          <span className={styles.keyChip}>⌘</span>
          <span className={styles.keyChip}>K</span>
        </button>
      </header>
      <nav className={styles.navigation} aria-label="Main navigation">
        {nav.map((group) => (
          <section key={group.label}>
            <button
              className={styles.groupHeading}
              type="button"
              aria-expanded={!collapsed[group.label]}
              aria-controls={`nav-${group.label.toLowerCase()}`}
              onClick={() =>
                setCollapsed((current) => ({
                  ...current,
                  [group.label]: !current[group.label],
                }))
              }
            >
              {group.label}
              <CaretDown
                className={collapsed[group.label] ? styles.collapsed : undefined}
                size={8}
                weight="bold"
                aria-hidden="true"
              />
            </button>
            <div id={`nav-${group.label.toLowerCase()}`} hidden={collapsed[group.label]}>
              {group.items.map(({ label, path, icon: Icon }) => (
                <NavLink
                  key={path}
                  to={path}
                  end
                  className={({ isActive }) =>
                    `${styles.item} ${isActive ? styles.active : ''}`
                  }
                >
                  <Icon size={16} weight="regular" aria-hidden="true" />
                  <span>{label}</span>
                </NavLink>
              ))}
            </div>
          </section>
        ))}
      </nav>
      <dialog
        ref={dialog}
        className={styles.palette}
        aria-label="Search navigation"
        onCancel={() => setOpen(false)}
        onClick={(event) => {
          if (event.target === event.currentTarget) setOpen(false)
        }}
      >
        <form
          onKeyDown={(event) => {
            if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
              event.preventDefault()
              if (filtered.length) {
                const direction = event.key === 'ArrowDown' ? 1 : -1
                setHighlightedIndex((current) =>
                  (current + direction + filtered.length) % filtered.length,
                )
              }
            } else if (event.key === 'Enter') {
              event.preventDefault()
              if (filtered[highlightedIndex]) select(filtered[highlightedIndex].path)
            }
          }}
          onSubmit={(event) => {
            event.preventDefault()
            if (filtered[highlightedIndex]) select(filtered[highlightedIndex].path)
          }}
        >
          <input
            className={styles.input}
            aria-label="Search pages"
            value={query}
            onChange={(event) => {
              setQuery(event.target.value)
              setHighlightedIndex(0)
            }}
            autoComplete="off"
          />
          <div className={styles.results}>
            {filtered.map(({ label, path, icon: Icon }, index) => (
              <button
                className={`${styles.result} ${index === highlightedIndex ? styles.highlighted : ''}`}
                key={path}
                type="button"
                onClick={() => select(path)}
              >
                <Icon size={16} weight="regular" aria-hidden="true" />
                {label}
              </button>
            ))}
          </div>
        </form>
      </dialog>
    </aside>
  )
}
