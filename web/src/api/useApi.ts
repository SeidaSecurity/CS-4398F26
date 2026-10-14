import { useCallback, useEffect, useRef, useState } from 'react'
import type { DependencyList } from 'react'

export function useApi<T>(fn: () => Promise<T>, deps: DependencyList) {
  const [data, setData] = useState<T>()
  const [error, setError] = useState<Error | null>(null)
  const [loading, setLoading] = useState(true)
  const [revision, setRevision] = useState(0)
  const fnRef = useRef(fn)
  fnRef.current = fn

  const reload = useCallback(() => setRevision(value => value + 1), [])

  useEffect(() => {
    let active = true
    setLoading(true)
    setError(null)
    Promise.resolve().then(() => fnRef.current()).then(
      result => {
        if (active) setData(result)
      },
      reason => {
        if (active) setError(reason instanceof Error ? reason : new Error(String(reason)))
      },
    ).finally(() => {
      if (active) setLoading(false)
    })
    return () => { active = false }
  }, [...deps, revision])

  return { data, error, loading, reload }
}
