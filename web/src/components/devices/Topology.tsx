import { useRef } from 'react'
import type { CSSProperties, MouseEvent } from 'react'
import { DeviceIllustration, deviceIllustrationHeight } from './DeviceIllustration'
import type { DeviceKind } from './DeviceIllustration'
import styles from './Topology.module.css'

export type TopologyNode = {
  id: number
  name: string
  kind: DeviceKind
  state: 'up' | 'down'
}

export type TopologyProps = {
  nodes: TopologyNode[]
  links: [number, number][]
  selectedId?: number
  onSelect?: (id: number) => void
  width?: number
}

const layerSpacing = 96
const illustrationWidth = 64
const illustrationInset = 2
const labelHeight = 16
const arcSpace = 22

export function Topology({ nodes, links, selectedId, onSelect, width = 248 }: TopologyProps) {
  const meshRef = useRef<HTMLDivElement>(null)
  const layoutWidth = Math.max(1, width)
  const adjacency = new Map(nodes.map(node => [node.id, new Set<number>()]))
  for (const [from, to] of links) {
    if (!adjacency.has(from) || !adjacency.has(to)) continue
    adjacency.get(from)!.add(to)
    adjacency.get(to)!.add(from)
  }
  const firewalls = nodes.filter(node => node.kind === 'firewall')
  const roots = firewalls.length ? firewalls : nodes.filter(node => node.kind === 'router')
  const depths = new Map(roots.map(node => [node.id, 0]))
  const queue = roots.map(node => node.id)
  for (let index = 0; index < queue.length; index++) {
    const id = queue[index]
    for (const neighbor of adjacency.get(id) ?? []) {
      if (depths.has(neighbor)) continue
      depths.set(neighbor, depths.get(id)! + 1)
      queue.push(neighbor)
    }
  }
  const lastDepth = depths.size ? Math.max(...depths.values()) + 1 : 0
  const layers: TopologyNode[][] = []
  for (const node of nodes) {
    const depth = depths.get(node.id) ?? lastDepth
    ;(layers[depth] ??= []).push(node)
  }
  for (let layerIndex = 1; layerIndex < layers.length; layerIndex++) {
    const previousLayer = layers[layerIndex - 1] ?? []
    const parentPositions = new Map(previousLayer.map((node, index) => [
      node.id, (index + 0.5) / previousLayer.length * layoutWidth,
    ]))
    const barycenters = new Map((layers[layerIndex] ?? []).map(node => {
      const parentXs = [...(adjacency.get(node.id) ?? [])]
        .filter(id => parentPositions.has(id))
        .map(id => parentPositions.get(id)!)
      return [node.id, parentXs.length
        ? parentXs.reduce((sum, x) => sum + x, 0) / parentXs.length
        : layoutWidth / 2]
    }))
    layers[layerIndex]?.sort((a, b) =>
      barycenters.get(a.id)! - barycenters.get(b.id)! || a.name.localeCompare(b.name))
  }
  const positionedNodes = layers.flatMap((layer, layerIndex) => layer.map((node, index) => ({
    node,
    x: (index + 0.5) / layer.length * layoutWidth,
    y: arcSpace + layerIndex * layerSpacing,
    illustrationHeight: deviceIllustrationHeight(node.kind, illustrationWidth),
    count: layer.length,
  })))
  const height = Math.max(64, ...positionedNodes.map(({ y, illustrationHeight }) => y + illustrationInset + illustrationHeight + labelHeight + 2))
  const positions = new Map(positionedNodes.map(position => [position.node.id, position]))

  function handleMouseMove(event: MouseEvent<HTMLDivElement>) {
    if (!meshRef.current || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    const bounds = event.currentTarget.getBoundingClientRect()
    if (!bounds.width || !bounds.height) return
    const horizontal = Math.max(-1, Math.min(1, (event.clientX - bounds.left) / bounds.width * 2 - 1))
    const vertical = Math.max(-1, Math.min(1, (event.clientY - bounds.top) / bounds.height * 2 - 1))
    meshRef.current.style.transform = `rotateX(${-vertical * 6}deg) rotateY(${horizontal * 6}deg)`
  }

  function resetTilt() {
    if (meshRef.current) meshRef.current.style.transform = 'rotateX(0deg) rotateY(0deg)'
  }

  return (
    <div className={styles.container} style={{ width: layoutWidth }} onMouseMove={handleMouseMove} onMouseLeave={resetTilt}>
      <div ref={meshRef} className={styles.mesh} style={{ height }}>
        <svg className={styles.links} width="100%" height={height} viewBox={`0 0 ${layoutWidth} ${height}`} preserveAspectRatio="none" aria-hidden="true">
          {links.map(([fromId, toId], index) => {
            const from = positions.get(fromId)
            const to = positions.get(toId)
            if (!from || !to) return null
            const down = from.node.state === 'down' || to.node.state === 'down'
            let path: string
            if (from.y === to.y) {
              const topY = from.y + illustrationInset
              path = `M ${from.x} ${topY} C ${from.x} ${topY - 24}, ${to.x} ${topY - 24}, ${to.x} ${topY}`
            } else {
              const upper = from.y < to.y ? from : to
              const lower = from.y < to.y ? to : from
              const startY = upper.y + illustrationInset + upper.illustrationHeight + labelHeight
              const endY = lower.y + illustrationInset
              const middleY = (startY + endY) / 2
              path = `M ${upper.x} ${startY} C ${upper.x} ${middleY}, ${lower.x} ${middleY}, ${lower.x} ${endY}`
            }
            return <path key={`${fromId}-${toId}-${index}`} className={down ? styles.downLink : undefined} d={path} fill="none" stroke={down ? '#fc8282' : '#c9ccd9'} strokeWidth="1" strokeDasharray={down ? '3 3' : undefined} vectorEffect="non-scaling-stroke" />
          })}
        </svg>
        {positionedNodes.map(({ node, x, y, count }) => (
          <div key={node.id} className={styles.position} style={{ left: `${x / layoutWidth * 100}%`, top: y, width: `calc(100% / ${count} - 4px)` }}>
            <button
              type="button"
              className={`${styles.node} ${selectedId === node.id ? styles.selected : ''}`}
              onClick={() => onSelect?.(node.id)}
              aria-label={`${node.name} · ${node.kind} · ${node.state}`}
              aria-pressed={selectedId === node.id}
              title={`${node.name} · ${node.state}`}
              style={{ '--status-color': node.state === 'up' ? 'var(--green-600, #1ca733)' : 'var(--red-600, #bb0f0f)' } as CSSProperties}
            >
              <DeviceIllustration kind={node.kind} state={node.state} width={illustrationWidth} />
              <span className={styles.label}>
                <span className={styles.status} aria-hidden="true" />
                <span className={styles.name}>{node.name}</span>
              </span>
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}

export default Topology
