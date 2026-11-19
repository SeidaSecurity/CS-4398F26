import { useMemo } from 'react'
import {
  Article,
  ChartLine,
  ClockCounterClockwise,
  Globe,
  HardDrives,
  UploadSimple,
  UsersThree,
} from '@phosphor-icons/react'
import type { Icon } from '@phosphor-icons/react'
import type { ReactNode } from 'react'
import { useAuth } from './auth'
import Network from './pages/Network'
import Logs from './pages/Logs'
import Devices from './pages/Devices'
import Push from './pages/Push'
import History from './pages/History'
import Accounts from './pages/Accounts'
import Services from './pages/Services'

type NavItem = {
  label: string
  path: string
  icon: Icon
  element: ReactNode
  /** Hidden from viewers (R7.2). The server enforces this too; hiding just keeps the UI honest. */
  adminOnly?: boolean
}

export const nav: { label: string; items: NavItem[] }[] = [
  {
    label: 'Insights',
    items: [
      { label: 'Network', path: '/', icon: ChartLine, element: <Network /> },
      { label: 'Logs', path: '/logs', icon: Article, element: <Logs /> },
    ],
  },
  {
    label: 'Inventory',
    items: [
      { label: 'Devices', path: '/devices', icon: HardDrives, element: <Devices /> },
    ],
  },
  {
    label: 'Configuration',
    items: [
      { label: 'Push', path: '/config/push', icon: UploadSimple, element: <Push />, adminOnly: true },
      {
        label: 'History',
        path: '/config/history',
        icon: ClockCounterClockwise,
        element: <History />,
      },
    ],
  },
  {
    label: 'Network services',
    items: [
      // Visible to viewers too (reads are allowed); the page hides write controls (R7.2).
      { label: 'Services', path: '/services', icon: Globe, element: <Services /> },
    ],
  },
  {
    label: 'Administration',
    items: [
      { label: 'Accounts', path: '/accounts', icon: UsersThree, element: <Accounts />, adminOnly: true },
    ],
  },
]

/** The navigation the signed-in user may see. */
export function useVisibleNav() {
  const { isAdmin } = useAuth()
  return useMemo(
    () => nav
      .map(group => ({ ...group, items: group.items.filter(item => isAdmin || !item.adminOnly) }))
      .filter(group => group.items.length > 0),
    [isAdmin],
  )
}
