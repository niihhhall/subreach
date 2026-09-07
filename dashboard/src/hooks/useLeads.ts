import { useCallback, useEffect, useState } from 'react'
import type { ApiLead, Lead } from '../types'
import { fetchJSON, hasValidConfig, isDemoMode } from '../lib/api'
import { adaptLead } from '../lib/adapters'
import { MOCK_LEADS } from '../lib/mockData'

// Loads leads from the reddit-outreach backend (/api/leads) and maps them to the
// dashboard's Lead shape. Falls back to mock data in demo mode.
export const useLeads = () => {
    const [leads, setLeads] = useState<Lead[]>([])
    const [isLoading, setIsLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)

    const fetchLeads = useCallback(async () => {
        if (isDemoMode) {
            setLeads(MOCK_LEADS)
            setIsLoading(false)
            return
        }
        if (!hasValidConfig()) {
            setIsLoading(false)
            return
        }
        try {
            setIsLoading(true)
            const data = await fetchJSON<{ leads: ApiLead[] }>('/leads')
            setLeads((data.leads || []).map(adaptLead))
            setError(null)
        } catch (err) {
            console.error('[useLeads] error:', err)
            setError(err instanceof Error ? err.message : String(err))
        } finally {
            setIsLoading(false)
        }
    }, [])

    useEffect(() => {
        fetchLeads()
    }, [fetchLeads])

    return { leads, isLoading, error, refetch: fetchLeads }
}
