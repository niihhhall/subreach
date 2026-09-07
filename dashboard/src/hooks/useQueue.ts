import { useCallback, useEffect, useState } from 'react'
import type { ApiQueueItem, Lead } from '../types'
import { fetchJSON, hasValidConfig, isDemoMode } from '../lib/api'
import { queueItemToLead } from '../lib/adapters'

// Loads the human-review queue (/api/queue) — approved + needs-revision drafts
// awaiting a send — mapped to the shared Lead shape so the detail view can show
// the original post and the drafted reply.
export const useQueue = () => {
    const [items, setItems] = useState<Lead[]>([])
    const [isLoading, setIsLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)

    const fetchQueue = useCallback(async () => {
        if (isDemoMode || !hasValidConfig()) {
            setIsLoading(false)
            return
        }
        try {
            setIsLoading(true)
            const data = await fetchJSON<{ items: ApiQueueItem[] }>('/queue')
            setItems((data.items || []).map(queueItemToLead))
            setError(null)
        } catch (err) {
            setError(err instanceof Error ? err.message : String(err))
        } finally {
            setIsLoading(false)
        }
    }, [])

    useEffect(() => {
        fetchQueue()
    }, [fetchQueue])

    return { items, isLoading, error, refetch: fetchQueue }
}
