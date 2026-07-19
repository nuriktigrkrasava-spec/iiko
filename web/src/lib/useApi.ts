import { useEffect, useState } from 'react'
import { apiGet } from './api'

export function useApi<T>(path: string, params: Record<string, string> = {}) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const key = path + JSON.stringify(params)

  useEffect(() => {
    let alive = true
    setLoading(true)
    setError(null)
    apiGet<T>(path, params)
      .then((d) => alive && setData(d))
      .catch((e) => alive && setError(String(e.message || e)))
      .finally(() => alive && setLoading(false))
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])

  return { data, error, loading }
}
