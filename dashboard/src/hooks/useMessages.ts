import { useCallback, useEffect, useState } from 'react'
import type { ApiEngagementItem, ApiQueueItem, Message } from '../types'
import { fetchJSON, isDemoMode } from '../lib/api'
import { MOCK_MESSAGES } from '../lib/mockData'

// The reddit-outreach backend has no chat log. We synthesize a "conversation"
// for a lead (post id) from the original post title (inbound) and our drafted
// reply (outbound), pulled from /api/queue and /api/engagement.
export const useMessages = (leadId?: string) => {
    const [messages, setMessages] = useState<Message[]>([])
    const [isLoading, setIsLoading] = useState(false)

    const fetchMessages = useCallback(async () => {
        if (!leadId) return
        if (isDemoMode) {
            setMessages(MOCK_MESSAGES.filter((m) => m.lead_id === leadId))
            return
        }
        try {
            setIsLoading(true)
            const [queue, engagement] = await Promise.all([
                fetchJSON<{ items: ApiQueueItem[] }>('/queue').catch(() => ({ items: [] })),
                fetchJSON<{ items: ApiEngagementItem[] }>('/engagement').catch(() => ({ items: [] })),
            ])
            const q = (queue.items || []).find((i) => i.id === leadId)
            const e = (engagement.items || []).find((i) => i.id === leadId)
            const title = q?.title || e?.title || ''
            const draft = q?.draft || e?.draft || ''
            const angle = e?.angle || ''

            const out: Message[] = []
            const inbound = title + (angle ? `\n\nAngle: ${angle}` : '')
            out.push({
                id: `${leadId}-post`,
                lead_id: leadId,
                direction: 'inbound',
                content: inbound || '(original Reddit post)',
                created_at: new Date().toISOString(),
            })
            if (draft) {
                out.push({
                    id: `${leadId}-draft`,
                    lead_id: leadId,
                    direction: 'outbound',
                    content: draft,
                    created_at: new Date().toISOString(),
                })
            }
            setMessages(out)
        } catch (err) {
            console.error('[useMessages] error:', err)
        } finally {
            setIsLoading(false)
        }
    }, [leadId])

    useEffect(() => {
        fetchMessages()
    }, [fetchMessages])

    return { messages, isLoading, refetch: fetchMessages }
}
