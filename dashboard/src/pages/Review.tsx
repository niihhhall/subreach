import React, { useState } from 'react'
import { LeadsList } from '../components/leads/LeadsList'
import { LeadDetail } from '../components/leads/LeadDetail'
import { useQueue } from '../hooks/useQueue'
import { Icon } from '@iconify/react'

// The human-review queue: approved + needs-revision drafts (/api/queue). Pick a
// row to read the original post and the compliance-checked drafted reply.
const Review: React.FC = () => {
    const { items, isLoading, refetch } = useQueue()
    const [selectedId, setSelectedId] = useState<string | null>(null)

    const selected = items.find((l) => l.id === selectedId) || items[0]

    return (
        <div className="h-[calc(100vh-72px)] flex overflow-hidden lg:p-8 lg:gap-6 animate-fade-up">
            <div className="w-full lg:w-[450px] flex-shrink-0 card lg:rounded-2xl overflow-hidden flex flex-col">
                <div className="p-8 border-b border-border bg-bg-elevated/40">
                    <h1 className="text-2xl font-bold tracking-tight text-ink flex items-center gap-3">
                        <div className="w-10 h-10 rounded-xl bg-brand-muted flex items-center justify-center text-brand">
                            <Icon icon="solar:clipboard-check-linear" width={22} />
                        </div>
                        Review <span className="text-brand">Queue</span>
                    </h1>
                    <p className="text-xs text-ink-muted mt-2">Compliance-checked drafts awaiting a human send</p>
                    <div className="flex items-center gap-2 mt-4 px-3 py-1.5 bg-brand-muted border border-brand/20 rounded-xl w-fit">
                        <div className="w-1.5 h-1.5 rounded-full bg-brand animate-pulse"></div>
                        <span className="text-xs font-semibold text-brand">{items.length} drafts to review</span>
                    </div>
                </div>
                <div className="flex-1 overflow-hidden">
                    <LeadsList
                        leads={items}
                        selectedId={selected?.id || null}
                        onSelect={setSelectedId}
                        isLoading={isLoading}
                        mode="conversations"
                    />
                </div>
            </div>

            <div className="hidden lg:flex flex-1 card rounded-2xl overflow-hidden relative">
                {selected ? (
                    <div className="w-full h-full">
                        <LeadDetail lead={selected} onClose={() => {}} refetch={refetch} />
                    </div>
                ) : (
                    <div className="absolute inset-0 flex flex-col items-center justify-center p-20 text-center space-y-6">
                        <div className="w-20 h-20 card rounded-2xl flex items-center justify-center">
                            <Icon icon="solar:clipboard-check-linear" width={32} className="text-ink-faint" />
                        </div>
                        <div className="space-y-2">
                            <h3 className="text-lg font-semibold text-ink tracking-tight">Queue is clear</h3>
                            <p className="text-sm text-ink-muted leading-relaxed max-w-[260px]">
                                No approved drafts waiting. Run the pipeline to generate outreach for review.
                            </p>
                        </div>
                    </div>
                )}
            </div>
        </div>
    )
}

export default Review
