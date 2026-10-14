import { useId } from 'react'

export type DeviceKind = 'router' | 'switch' | 'firewall'

export type DeviceIllustrationProps = {
  kind: DeviceKind
  state?: 'up' | 'down'
  width?: number
}

type Point3D = [number, number, number]

const dimensions = {
  switch: { W: 140, D: 70, H: 10 },
  router: { W: 90, D: 60, H: 12 },
  firewall: { W: 70, D: 60, H: 22 },
}

function iso(x: number, y: number, z: number): [number, number] {
  return [(x - y) * 0.866, (x + y) * 0.5 - z]
}

function polygon(points: Point3D[]) {
  return points.map(point => iso(...point).join(',')).join(' ')
}

function frontRect(x: number, z: number, width: number, height: number, y = 0) {
  return polygon([[x, y, z], [x + width, y, z], [x + width, y, z + height], [x, y, z + height]])
}

function frontCircle(x: number, z: number, radius: number, y = 0) {
  return polygon(Array.from({ length: 24 }, (_, index): Point3D => {
    const angle = index / 24 * Math.PI * 2
    return [x + Math.cos(angle) * radius, y, z + Math.sin(angle) * radius]
  }))
}

function bounds(kind: DeviceKind) {
  const { W, D, H } = dimensions[kind]
  const ear = kind === 'switch' ? 6 : 0
  const minX = -ear * 0.866 - 12
  const minY = -D * 0.5 - H - 4
  const width = (W + D + ear) * 0.866 + 24
  const height = (W + D) * 0.5 + H + 22
  return { minX, minY, width, height }
}

export function deviceIllustrationHeight(kind: DeviceKind, width: number) {
  const box = bounds(kind)
  return width * box.height / box.width
}

export function DeviceIllustration({ kind, state = 'up', width = 72 }: DeviceIllustrationProps) {
  const id = useId().replace(/[^a-zA-Z0-9_-]/g, '')
  const shadowId = `device-shadow-${id}`
  const glowId = `device-glow-${id}`
  const { W, D, H } = dimensions[kind]
  const box = bounds(kind)
  const ledColor = state === 'up' ? 'var(--green-600, #1ca733)' : 'var(--red-600, #bb0f0f)'
  // The enclosure extends into negative y, away from its front panel at y = 0.
  const shadowCenter = iso(W / 2, -D / 2, -5)

  function port(x: number, z: number, portWidth: number, portHeight: number, key: number, led = true) {
    return (
      <g key={key}>
        <polygon points={frontRect(x, z, portWidth, portHeight)} fill="#1e202e" stroke="#4e5161" strokeWidth="0.5" />
        <polyline points={polygon([[x + 0.6, 0, z + 0.6], [x + portWidth - 0.6, 0, z + 0.6], [x + portWidth - 0.6, 0, z + portHeight - 0.6]])} stroke="#4e5161" strokeWidth="0.5" />
        {led && <polygon points={frontRect(x + 0.5, z + portHeight + 0.35, 0.9, 0.45)} fill="var(--green-600, #1ca733)" />}
      </g>
    )
  }

  return (
    <svg width={width} height={deviceIllustrationHeight(kind, width)} viewBox={`${box.minX} ${box.minY} ${box.width} ${box.height}`} fill="none" role="img" aria-label={`${kind} · ${state}`} style={{ display: 'block', flexShrink: 0, opacity: state === 'down' ? 0.55 : 1, filter: state === 'down' ? 'grayscale(0.6)' : undefined }}>
      <defs>
        <filter id={shadowId} x="-30%" y="-100%" width="160%" height="300%">
          <feGaussianBlur stdDeviation="6" />
        </filter>
        <filter id={glowId} x="-200%" y="-200%" width="500%" height="500%">
          <feGaussianBlur stdDeviation="1.2" />
        </filter>
      </defs>
      <ellipse cx={shadowCenter[0]} cy={shadowCenter[1]} rx={(W + D) * 0.866 * 0.43} ry={(W + D) * 0.5 * 0.38} fill="#5461c8" opacity="0.1" filter={`url(#${shadowId})`} />
      <g stroke="#c9ccd9" strokeWidth="0.75" strokeLinejoin="round">
        <polygon points={polygon([[0, 0, H], [W, 0, H], [W, -D, H], [0, -D, H]])} fill="#ffffff" />
        <polygon points={polygon([[W, 0, 0], [W, -D, 0], [W, -D, H], [W, 0, H]])} fill="#e6e8f0" />
        <polygon points={frontRect(0, 0, W, H)} fill="#f3f4f8" />
        {kind === 'switch' && [-6, W].map(x => (
          <g key={x}>
            <polygon points={frontRect(x, 0, 6, H)} fill="#f3f4f8" />
            <polygon points={frontCircle(x + 3, H / 2, 1.3)} fill="#a5a9bb" strokeWidth="0.5" />
          </g>
        ))}
      </g>
      <line x1={iso(3, 0, H - 2)[0]} y1={iso(3, 0, H - 2)[1]} x2={iso(8, 0, H - 2)[0]} y2={iso(8, 0, H - 2)[1]} stroke="var(--brand-500, #6977e1)" strokeWidth="1" strokeLinecap="round" />
      {kind === 'switch' && (
        <>
          {Array.from({ length: 24 }, (_, index) => port(15 + index % 12 * 7.2, 1.1 + Math.floor(index / 12) * 4.3, 5.3, 3, index))}
          {Array.from({ length: 4 }, (_, index) => port(106 + index * 7.2, 2.1, 5.4, 5.6, index, false))}
        </>
      )}
      {kind === 'router' && (
        <>
          {Array.from({ length: 4 }, (_, index) => port(17 + index * 10, 2.4, 7, 6, index))}
          {Array.from({ length: 8 }, (_, index) => <polygon key={index} points={frontRect(62 + index * 2.6, 2.4, 0.8, 6.5)} fill="#9296aa" />)}
        </>
      )}
      {kind === 'firewall' && (
        <>
          {Array.from({ length: 2 }, (_, index) => port(15 + index * 13, 11, 9, 7, index))}
          {Array.from({ length: 4 }, (_, index) => <polygon key={index} points={frontRect(15, 2.5 + index * 1.7, 29, 0.6)} fill="#9296aa" />)}
          <polygon points={frontRect(51, 7, 12, 9)} fill="#1e202e" stroke="#4e5161" strokeWidth="0.5" />
          <polygon points={frontRect(53, 9, 3, 1)} fill="var(--green-600, #1ca733)" />
          <polygon points={frontRect(53, 12, 7, 0.6)} fill="#9296aa" />
        </>
      )}
      <polygon points={frontCircle(5.5, H / 2 - 0.5, 1.5)} fill={ledColor} opacity="0.5" filter={`url(#${glowId})`} />
      <polygon points={frontCircle(5.5, H / 2 - 0.5, 0.85)} fill={ledColor} />
    </svg>
  )
}

export default DeviceIllustration
