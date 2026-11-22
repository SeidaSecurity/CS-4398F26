// Mock mode only: stands in for the server's diff (app/config_diff.py, R3.4), which is a
// line-for-line port of this function checked against fixtures captured from it.
import type { DiffLine, DiffRow } from './types'

export function sideBySide(a: string, b: string): { rows: DiffRow[]; added: number; removed: number } {
  const left = a === '' ? [] : a.split(/\r?\n/)
  const right = b === '' ? [] : b.split(/\r?\n/)
  const lcs = Array.from({ length: left.length + 1 }, () => new Uint32Array(right.length + 1))

  for (let i = left.length - 1; i >= 0; i--) {
    for (let j = right.length - 1; j >= 0; j--) {
      lcs[i][j] = left[i] === right[j]
        ? lcs[i + 1][j + 1] + 1
        : Math.max(lcs[i + 1][j], lcs[i][j + 1])
    }
  }

  const rows: DiffRow[] = []
  let i = 0
  let j = 0
  let added = 0
  let removed = 0

  while (i < left.length || j < right.length) {
    if (i < left.length && j < right.length && left[i] === right[j]) {
      rows.push({ kind: 'same', left: { n: i + 1, text: left[i] }, right: { n: j + 1, text: right[j] } })
      i++
      j++
      continue
    }

    const deletions: DiffLine[] = []
    const additions: DiffLine[] = []
    while ((i < left.length || j < right.length)
      && !(i < left.length && j < right.length && left[i] === right[j])) {
      if (i < left.length && (j === right.length || lcs[i + 1][j] >= lcs[i][j + 1])) {
        deletions.push({ n: i + 1, text: left[i++] })
        removed++
      } else {
        additions.push({ n: j + 1, text: right[j++] })
        added++
      }
    }

    for (let k = 0; k < Math.max(deletions.length, additions.length); k++) {
      rows.push({
        left: deletions[k],
        right: additions[k],
        kind: deletions[k] && additions[k] ? 'changed' : deletions[k] ? 'removed' : 'added',
      })
    }
  }

  return { rows, added, removed }
}
