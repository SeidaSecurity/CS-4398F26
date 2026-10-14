import styles from './PortGrid.module.css'

export type PortGridProps = {
  ports: { index: number; name: string; up: boolean }[]
}

export function PortGrid({ ports }: PortGridProps) {
  const sortedPorts = [...ports].sort((a, b) => a.index - b.index)

  return (
    <div className={styles.card} aria-label="Port status" style={{ gridTemplateColumns: `repeat(${Math.max(1, Math.ceil(ports.length / 2))}, minmax(0, 22px))` }}>
      {[1, 0].flatMap((parity, row) =>
        sortedPorts.filter(port => port.index % 2 === parity).map((port, column) => (
          <span key={port.index} className={`${styles.chip} ${port.up ? styles.up : styles.down}`} style={{ gridRow: row + 1, gridColumn: column + 1 }} title={`${port.name} · ${port.up ? 'up' : 'down'}`}>
            {port.index}
          </span>
        )),
      )}
    </div>
  )
}

export default PortGrid
