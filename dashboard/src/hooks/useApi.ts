import { useEffect, useState } from 'react'
import { fetchJSON, isDemoMode } from '../lib/api'

// Generic read hook. Fetches `/api<path>` and auto-refreshes every 30s so the
// dashboard stays live (the backend is REST/read-only, no websockets).
export function useApi<T = unknown>(path: string, params: Record<string, string> = {}) {
    const [data, setData] = useState<T | null>(null)
    const [error, setError] = useState<string>('')
    const [isLoading, setIsLoading] = useState(true)
    const key = JSON.stringify(params)

    useEffect(() => {
        if (isDemoMode) {
            setIsLoading(false)
            return
        }
        let alive = true
        const load = (first: boolean) => {
            if (first) setIsLoading(true)
            fetchJSON<T>(path, params)
                .then((d) => {
                    if (!alive) return
                    setData(d)
                    setError('')
                })
                .catch((e) => {
                    if (alive) setError(String(e))
                })
                .finally(() => {
                    if (alive && first) setIsLoading(false)
                })
        }
        load(true)
        const id = setInterval(() => load(false), 30000)
        return () => {
            alive = false
            clearInterval(id)
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [path, key])

    return { data, isLoading, error }
}
