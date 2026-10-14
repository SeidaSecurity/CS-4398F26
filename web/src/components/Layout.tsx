import { createContext, useContext, useEffect, useState } from 'react'
import type { Dispatch, ReactNode, SetStateAction } from 'react'
import { useLocation } from 'react-router-dom'
import { nav } from '../nav'
import Sidebar from './Sidebar'
import styles from './Layout.module.css'

const RightPanelContext = createContext<Dispatch<SetStateAction<ReactNode>> | null>(null)

export function RightPanel({ children }: { children: ReactNode }) {
  const setPanel = useContext(RightPanelContext)

  useEffect(() => {
    setPanel?.(children)
    return () => setPanel?.(null)
  }, [children, setPanel])

  return null
}

export default function Layout({ children }: { children: ReactNode }) {
  const [panel, setPanel] = useState<ReactNode>(null)
  const hasPanel = panel !== null && panel !== undefined && panel !== false
  const { pathname } = useLocation()
  const currentItem = nav.flatMap((group) => group.items).find((item) => item.path === pathname)
  const Icon = currentItem?.icon

  return (
    <RightPanelContext.Provider value={setPanel}>
      <div className={`${styles.layout} ${hasPanel ? styles.withPanel : ''}`}>
        <Sidebar />
        <header className={styles.header}>
          {Icon && <Icon size={16} weight="regular" aria-hidden="true" />}
          <h1 className={styles.title}>{currentItem?.label}</h1>
        </header>
        <main className={styles.center}>{children}</main>
        {hasPanel && <aside className={styles.rightPanel}>{panel}</aside>}
      </div>
    </RightPanelContext.Provider>
  )
}
