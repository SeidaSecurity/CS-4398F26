import {
  Article,
  ChartLine,
  ClockCounterClockwise,
  HardDrives,
  UploadSimple,
} from '@phosphor-icons/react'
import Network from './pages/Network'
import Logs from './pages/Logs'
import Devices from './pages/Devices'
import Push from './pages/Push'
import History from './pages/History'

export const nav = [
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
      { label: 'Push', path: '/config/push', icon: UploadSimple, element: <Push /> },
      {
        label: 'History',
        path: '/config/history',
        icon: ClockCounterClockwise,
        element: <History />,
      },
    ],
  },
]
