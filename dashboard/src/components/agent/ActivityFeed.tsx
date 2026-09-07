import React, { useEffect, useState, useCallback } from 'react'
import { fetchJSON, isDemoMode } from '../../lib/api'
import { MOCK_MESSAGES } from '../../lib/mockData'
import type { ApiActivity } from '../../types'
import { Icon } from '@iconify/react'

// Live event log from the reddit-outreach backend (/api/activity). Each row is
// an action the agent took: discovery, comment, reply, dm, post, handoff, verify.
export const ActivityFeed: React.FC = () => {
    const [items, setItems] = useState<ApiActivity[]>([])
    const [isLoading, setIsLoading] = useState(true)

    const fetchLatest = useCallback(async () => {
        if (isDemoMode) {
            setItems(
                MOCK_MESSAGES.map((m) => ({
                    ts: new Date(m.created_at).getTime() / 1000,
                    action: m.direction === 'inbound' ? 'discovered' : 'sent',
                    channel: 'comment',
                    detail: m.content,
                    status: 'posted',
                }))
            )
            setIsLoading(false)
            return
        }
        try {
            const data = await fetchJSON<{ items: ApiActivity[] }>('/activity')
            setItems((data.items || []).slice(0, 25))
        } catch (err) {
            console.error('[ActivityFeed] error:', err)
        } finally {
            setIsLoading(false)
        }
    }, [])

    useEffect(() => {
        fetchLatest()
        if (isDemoMode) return
        const id = setInterval(fetchLatest, 30000)
        return () => clearInterval(id)
    }, [fetchLatest])

    if (isLoading && items.length === 0)
        return (
            <div className="space-y-4">
                {Array.from({ length: 5 }).map((_, i) => (
                    <div key={i} className="h-16 bg-bg-elevated rounded-2xl animate-pulse border border-border"></div>
                ))}
            </div>
        )

    const label = (a: ApiActivity) => {
        const act = (a.action || '').toLowerCase()
        if (act === 'sent') return a.channel === 'dm' ? 'Direct Message Sent' : a.channel === 'post' ? 'Post Published' : 'Comment Sent'
        if (act === 'handoff') return 'Lead Handed Off'
        if (act === 'verify') return 'Send Verified'
        if (act === 'discovered') return 'Lead Discovered'
        return a.action || 'Activity'
    }

    return (
        <div className="space-y-6">
            <div className="card overflow-hidden">
                <div className="px-6 py-4 border-b border-border bg-bg-elevated flex items-center justify-between">
                    <div className="flex items-center gap-3">
                        <div className="w-8 h-8 rounded-lg bg-brand-muted flex items-center justify-center text-brand">
                            <Icon icon="solar:activity-linear" width={16} />
                        </div>
                        <span className="text-sm font-semibold tracking-tight text-ink">Activity Telemetry</span>
                    </div>
                    <div className="flex items-center gap-6">
                        <div className="flex items-center gap-2 text-xs font-medium text-ink-muted">
                            <div className="w-2 h-2 rounded-full bg-brand" /> outreach
                        </div>
                        <div className="flex items-center gap-2 text-xs font-medium text-ink-muted">
                            <div className="w-2 h-2 rounded-full bg-violet-500" /> system
                        </div>
                    </div>
                </div>

                <div className="divide-y divide-border max-h-[600px] overflow-y-auto custom-scrollbar">
                    {items.map((item, idx) => {
                        const isSend = (item.action || '').toLowerCase() === 'sent'
                        return (
                            <div
                                key={idx}
                                className="px-6 py-5 flex items-center justify-between group hover:bg-bg-elevated transition-colors animate-fade-up"
                                style={{ animationDelay: `${idx * 40}ms` }}
                            >
                                <div className="flex items-center gap-5 min-w-0">
                                    <div
                                        className={`w-11 h-11 rounded-xl flex items-center justify-center border shrink-0 transition-transform duration-300 group-hover:scale-105 ${
                                            isSend
                                                ? 'bg-brand-muted text-brand border-brand/20'
                                                : 'bg-violet-50 text-violet-600 border-violet-100'
                                        }`}
                                    >
                                        {isSend ? <Icon icon="solar:chat-round-dots-linear" width={20} /> : <Icon icon="solar:cpu-bolt-linear" width={20} />}
                                    </div>

                                    <div className="min-w-0">
                                        <div className="flex items-center gap-3">
                                            <p className="text-sm font-semibold text-ink tracking-tight">{label(item)}</p>
                                            {item.ts && (
                                                <span className="text-xs text-ink-faint shrink-0 pt-0.5">
                                                    / {new Date(item.ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                                                </span>
                                            )}
                                        </div>

                                        <p className="text-xs text-ink-muted truncate mt-1 max-w-[350px] md:max-w-[700px] leading-relaxed">
                                            {item.subreddit ? `r/${item.subreddit}` : ''}
                                            {item.author ? ` · u/${item.author}` : ''}
                                            {item.detail ? ` · ${item.detail}` : ''}
                                        </p>
                                    </div>
                                </div>

                                <div className="flex items-center gap-6 shrink-0 ml-6">
                                    {item.status && (
                                        <div
                                            className={`px-3 py-1 rounded-full text-[11px] font-medium border ${
                                                item.status === 'posted' || item.status === 'sent' || item.status === 'visible'
                                                    ? 'bg-brand-muted text-brand border-brand/20'
                                                    : 'bg-gray-50 text-ink-muted border-gray-200'
                                            }`}
                                        >
                                            {item.status}
                                        </div>
                                    )}
                                </div>
                            </div>
                        )
                    })}
                    {!isLoading && items.length === 0 && (
                        <div className="py-20 text-center text-sm text-ink-muted">No activity recorded yet</div>
                    )}
                </div>
            </div>
        </div>
    )
}
