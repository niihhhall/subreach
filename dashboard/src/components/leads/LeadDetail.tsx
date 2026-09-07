import React, { useMemo, useState } from 'react'
import type { Lead } from '../../types'
import { Badge } from '../ui/Badge'
import { SegmentedControl } from '../ui/SegmentedControl'
import { ConversationView } from './ConversationView'
import { IntelligenceView } from './IntelligenceView'
import { useMessages } from '../../hooks/useMessages'
import { adaptState, capitalizeFirst } from '../../lib/adapters'
import { Icon } from '@iconify/react'

interface LeadDetailProps {
    lead: Lead
    onClose: () => void
    refetch: () => void
}

export const LeadDetail: React.FC<LeadDetailProps> = ({ lead, onClose, refetch }) => {
    const [activeTab, setActiveTab] = useState('conversation')
    const { messages } = useMessages(lead.id)
    // Conversation state is synthesized from the lead's pipeline stage/tier.
    const state = useMemo(() => adaptState(lead), [lead])

    const handleUpdate = () => {
        refetch()
    }

    return (
        <div className="flex flex-col h-full bg-white relative custom-scrollbar overflow-y-auto overflow-x-hidden">
            <div className="flex items-center justify-between p-8 border-b border-border sticky top-0 z-20 bg-white">
                <div className="flex items-center gap-4">
                    <div className="w-14 h-14 rounded-2xl bg-brand flex items-center justify-center text-white shadow-card shrink-0">
                        <Icon icon="solar:users-group-rounded-bold" width={28} />
                    </div>
                    <div className="min-w-0">
                        <h2 className="text-xl font-bold tracking-tight text-ink line-clamp-2">{lead.title || lead.first_name}</h2>
                        <div className="flex items-center gap-3 mt-2">
                            <Badge variant="temperature" value={lead.temperature} />
                            <span className="text-xs font-medium text-ink-muted">{lead.subreddit ? `r/${lead.subreddit}` : ''}</span>
                        </div>
                    </div>
                </div>
                <div className="flex items-center gap-3 shrink-0">
                    {lead.url && (
                        <a
                            href={lead.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="btn-secondary group"
                            title="Open this post on Reddit"
                        >
                            <div className="flex items-center gap-2">
                                <Icon icon="solar:arrow-right-up-linear" width={16} className="group-hover:translate-x-0.5 group-hover:-translate-y-0.5 transition-transform" />
                                <span className="hidden sm:inline font-semibold">View on Reddit</span>
                            </div>
                        </a>
                    )}
                    <button
                        onClick={onClose}
                        className="w-10 h-10 flex items-center justify-center hover:bg-bg-elevated rounded-xl transition-all duration-200 text-ink-faint hover:text-ink border border-transparent hover:border-border"
                    >
                        <Icon icon="solar:close-circle-linear" width={24} />
                    </button>
                </div>
            </div>

            <div className="p-8 border-b border-border grid grid-cols-3 gap-4">
                <div className="p-4 rounded-xl bg-white border border-border">
                    <p className="text-[10px] font-medium text-ink-faint mb-1">Subreddit</p>
                    <p className="text-sm font-semibold text-ink tracking-tight truncate">{lead.subreddit ? `r/${lead.subreddit}` : '—'}</p>
                </div>
                <div className="p-4 rounded-xl bg-white border border-border">
                    <p className="text-[10px] font-medium text-ink-faint mb-1">Priority</p>
                    <p className="text-sm font-semibold text-ink tracking-tight">P{lead.priority ?? lead.signal_score * 10}</p>
                </div>
                <div className="p-4 rounded-xl bg-white border border-border">
                    <p className="text-[10px] font-medium text-ink-faint mb-1">Comments</p>
                    <p className="text-sm font-semibold text-ink tracking-tight">{lead.num_comments ?? '—'}</p>
                </div>
            </div>

            <div className="px-8 py-6">
                <SegmentedControl
                    options={[
                        { id: 'conversation', label: 'Post & Draft', icon: 'solar:chat-square-linear' },
                        { id: 'intelligence', label: 'Signals', icon: 'solar:graph-up-linear' },
                        { id: 'profile', label: 'Details', icon: 'solar:document-text-linear' }
                    ]}
                    activeId={activeTab}
                    onChange={setActiveTab}
                />
            </div>

            <div className="flex-1 overflow-hidden px-8 pb-8">
                {activeTab === 'conversation' && (
                    <ConversationView
                        lead={lead}
                        messages={messages}
                        state={state}
                    />
                )}
                {activeTab === 'intelligence' && (
                    <IntelligenceView
                        lead={lead}
                        state={state}
                        onUpdate={handleUpdate}
                    />
                )}
                {activeTab === 'profile' && (
                    <div className="space-y-8 animate-fade-up">
                        <section className="space-y-4">
                            <h3 className="text-xs font-semibold text-ink-muted flex items-center gap-2">
                                Core Details
                            </h3>
                            <div className="grid grid-cols-2 gap-4">
                                <div className="bg-white p-5 rounded-xl border border-border">
                                    <p className="text-[11px] text-ink-faint font-medium mb-1.5">Post ID</p>
                                    <p className="text-xs font-semibold text-ink truncate">{lead.id}</p>
                                </div>
                                <div className="bg-white p-5 rounded-xl border border-border">
                                    <p className="text-[11px] text-ink-faint font-medium mb-1.5">Created</p>
                                    <p className="text-xs font-semibold text-ink">{new Date(lead.created_at).toLocaleString()}</p>
                                </div>
                            </div>
                        </section>

                        {(lead.pains && lead.pains.length > 0) && (
                            <section className="space-y-4">
                                <h3 className="text-xs font-semibold text-ink-muted">Pain points</h3>
                                <div className="flex flex-wrap gap-2">
                                    {lead.pains.map((p) => (
                                        <span key={p} className="text-xs font-medium px-3 py-1.5 bg-bg-elevated text-ink-soft rounded-lg border border-border">
                                            {capitalizeFirst(p)}
                                        </span>
                                    ))}
                                </div>
                            </section>
                        )}

                        {lead.url && (
                            <a
                                href={lead.url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="bg-brand-muted rounded-2xl flex items-center justify-between p-6 border-l-4 border-l-brand group"
                            >
                                <div className="flex items-center gap-4">
                                    <div className="w-12 h-12 bg-white rounded-xl flex items-center justify-center text-brand shadow-card">
                                        <Icon icon="solar:link-circle-linear" width={24} />
                                    </div>
                                    <div>
                                        <p className="text-base font-semibold text-ink tracking-tight">Open the original thread</p>
                                        <p className="text-xs text-ink-muted mt-0.5">Read the full post and comments on Reddit</p>
                                    </div>
                                </div>
                                <Icon icon="solar:arrow-right-up-linear" width={20} className="text-brand group-hover:translate-x-0.5 group-hover:-translate-y-0.5 transition-transform" />
                            </a>
                        )}
                    </div>
                )}
            </div>
        </div>
    )
}
