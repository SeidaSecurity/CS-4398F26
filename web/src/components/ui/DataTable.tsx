import { isValidElement } from 'react'
import type { CSSProperties, Key, ReactNode } from 'react'
import styles from './DataTable.module.css'

export type DataTableColumn<Row extends object> = {
  key: keyof Row & string
  header: ReactNode
  width?: CSSProperties['width']
  render?: (value: Row[keyof Row], row: Row, index: number) => ReactNode
}

export type DataTableProps<Row extends object> = {
  columns: DataTableColumn<Row>[]
  rows: Row[]
  rowKey: keyof Row | ((row: Row) => Key)
  onRowClick?: (row: Row) => void
  selectedKey?: Key
  className?: string
  'aria-label'?: string
}

function renderValue(value: unknown): ReactNode {
  if (value == null) return null
  if (isValidElement(value)) return value
  return String(value)
}

export function DataTable<Row extends object>({ columns, rows, rowKey, onRowClick, selectedKey, className, 'aria-label': label }: DataTableProps<Row>) {
  return (
    <div className={[styles.container, className].filter(Boolean).join(' ')}>
      <table className={styles.table} aria-label={label}>
        <colgroup>
          {columns.map((column) => <col key={column.key} style={{ width: column.width }} />)}
        </colgroup>
        <thead>
          <tr>
            {columns.map((column) => <th key={column.key} scope="col">{column.header}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => {
            const key = typeof rowKey === 'function' ? rowKey(row) : row[rowKey] as Key
            const selected = selectedKey !== undefined && key === selectedKey
            return (
              <tr
                key={key}
                className={[styles.row, selected ? styles.selected : '', onRowClick ? styles.clickable : ''].filter(Boolean).join(' ')}
                aria-selected={selectedKey !== undefined ? selected : undefined}
                tabIndex={onRowClick ? 0 : undefined}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                onKeyDown={onRowClick ? (event) => {
                  if (event.target !== event.currentTarget) return
                  if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault()
                    onRowClick(row)
                  }
                } : undefined}
              >
                {columns.map((column) => (
                  <td key={column.key}>{column.render ? column.render(row[column.key], row, index) : renderValue(row[column.key])}</td>
                ))}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export default DataTable
