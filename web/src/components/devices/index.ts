export { DeviceIllustration } from './DeviceIllustration'
export type { DeviceIllustrationProps, DeviceKind } from './DeviceIllustration'
export { PortGrid } from './PortGrid'
export type { PortGridProps } from './PortGrid'
export { Topology } from './Topology'
export type { TopologyNode, TopologyProps } from './Topology'

import type { DeviceKind } from './DeviceIllustration'

export function deviceKind(name: string, platform: string): DeviceKind {
  // Keep the platform argument for callers that already have both device fields.
  void platform
  if (name.startsWith('SW')) return 'switch'
  if (name.startsWith('FW')) return 'firewall'
  return 'router'
}
