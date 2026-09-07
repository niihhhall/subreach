import React, { useEffect, useRef } from 'react'
import type { Lead, Message, ConversationState } from '../../types'
import { Badge } from '../ui/Badge'
import { Icon } from '@iconify/react'

interface ConversationViewProps {
    messages: Message[]
    isLoading?: boolean
    lead: Lead
    state: ConversationState | null
}

// Shows the discovered Reddit post (inbound) and our drafted reply (outbound).
// The draft is a dry-run preview — sending happens from the CLI (Phase 2).
export const ConversationView: React.FC<ConversationViewProps> = ({ messages, isLoading, lead, state }) => {
    void lead
    const currentState = state?.current_state || 'Discovery'
    const scrollRef = useRef<HTMLDivElement>(null)

    useEffect(() => {
        if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }, [messages])

    const hasDraft = messages.some((m) => m.direction === 'outbound')

    return (
        <div className="flex flex-col h-full animate-fade-up relative">
            <div className="flex items-center justify-between mb-6 px-1">
                <div className="flex items-center gap-3">
                    <Badge variant="state" value={currentState} />
                    <span className="text-xs text-ink-muted">
                        {hasDraft ? 'post + drafted reply' : 'post — no draft yet'}
                    </span>
                </div>
            </div>

            <div
                ref={scrollRef}
                className="flex-1 overflow-y-auto pr-4 space-y-4 custom-scrollbar pb-8 bg-bg-elevated/40 rounded-2xl p-4"
            >
                {isLoading ? (
                    Array.from({ length: 2 }).map((_, i) => (
                        <div key={i} className={`flex ${i % 2 === 0 ? 'justify-start' : 'justify-end'} animate-pulse opacity-50`}>
                            <div className={`w-2/3 h-16 rounded-2xl ${i % 2 === 0 ? 'bg-gray-100 border border-border' : 'bg-brand/30'}`} />
                        </div>
                    ))
                ) : (
                    messages.map((msg, i) => {
                        const isDraft = msg.direction === 'outbound'
                        return (
                            <div key={msg.id || i} className={`flex ${isDraft ? 'justify-end' : 'justify-start'} animate-fade-up`} style={{ animationDelay: `${i * 40}ms` }}>
                                <div
                                    className={`max-w-[85%] px-5 py-3.5 text-sm leading-relaxed whitespace-pre-wrap ${
                                        isDraft
                                            ? 'bg-brand text-white rounded-2xl rounded-br-md shadow-card'
                                            : 'bg-white border border-border text-ink rounded-2xl rounded-bl-md'
                                    }`}
                                >
                                    {msg.content}
                                    <div className={`text-[10px] mt-2 flex items-center gap-2 font-semibold ${isDraft ? 'text-white/70' : 'text-ink-faint'}`}>
                                        <Icon icon={isDraft ? 'solar:pen-new-square-linear' : 'solar:hashtag-linear'} width={11} />
                                        <span>{isDraft ? 'Drafted reply' : 'Original post'}</span>
                                    </div>
                                </div>
                            </div>
                        )
                    })
                )}

                {!isLoading && messages.length === 0 && (
                    <div className="h-full flex flex-col items-center justify-center py-32 text-center space-y-4">
                        <div className="w-20 h-20 bg-white border border-border rounded-full flex items-center justify-center">
                            <Icon icon="solar:chat-round-dots-linear" width={32} className="text-ink-faint" />
                        </div>
                        <p className="text-sm text-ink-muted">Nothing drafted for this post yet</p>
                    </div>
                )}
            </div>

            <div className="pt-6 mt-4 border-t border-border">
                <div className="card rounded-xl px-5 py-3.5 flex items-center justify-between">
                    <div className="flex items-center gap-3">
                        <div className="w-2 h-2 rounded-full bg-amber-500"></div>
                        <span className="text-xs text-ink-muted">Draft preview — nothing is posted</span>
                    </div>
                    <div className="flex items-center gap-2 px-3 py-1 bg-bg-elevated rounded-lg border border-border">
                        <Icon icon="solar:command-linear" width={13} className="text-brand" />
                        <span className="text-[11px] font-semibold text-ink-soft">Send via CLI (Phase 2)</span>
                    </div>
                </div>
            </div>
        </div>
    )
}
