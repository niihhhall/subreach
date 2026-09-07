import React from 'react'
import type { Lead } from '../../types'
import { Badge } from '../ui/Badge'
import { capitalizeFirst } from '../../lib/adapters'
import { Icon } from '@iconify/react'

interface LeadCardProps {
    lead: Lead
    active?: boolean
    onClick: () => void
    variant?: 'compact' | 'full'
    showState?: boolean
}

function ageLabel(iso: string): string {
    const mins = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 60000))
    if (mins < 60) return `${mins}m ago`
    const hrs = Math.floor(mins / 60)
    if (hrs < 24) return `${hrs}h ago`
    return `${Math.floor(hrs / 24)}d ago`
}

// A Reddit prospect: the discovered post. Heading is the post title; identity is
// the subreddit; priority/tier + pain points drive the visual weight.
export const LeadCard: React.FC<LeadCardProps> = ({ lead, active, onClick, variant = 'full' }) => {
    const isCompact = variant === 'compact'
    const title = lead.title || lead.first_name || 'Untitled post'
    const sub = lead.subreddit ? `r/${lead.subreddit}` : ''
    const pains = (lead.pains || []).slice(0, isCompact ? 1 : 2)

    return (
        <button
            onClick={onClick}
            className={`w-full text-left p-5 rounded-xl border transition-all duration-200 relative overflow-hidden group
                ${active ? 'bg-brand-muted border-brand/30 shadow-card' : 'bg-white border-border hover:border-brand/30 hover:shadow-lift'}`}
        >
            {active && <div className="absolute left-0 top-0 bottom-0 w-1 bg-brand rounded-r-full"></div>}

            <div className="flex items-center justify-between gap-3 mb-3">
                <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-[11px] font-semibold tracking-wide border border-brand/15 bg-brand-muted text-brand whitespace-nowrap max-w-[70%] truncate">
                    {sub || 'unknown'}
                </span>
                <Badge variant="temperature" value={lead.temperature} />
            </div>

            <h4 className={`font-semibold tracking-tight text-ink mb-3 ${isCompact ? 'text-sm line-clamp-2' : 'text-[15px] line-clamp-2'}`}>
                {title}
            </h4>

            {pains.length > 0 && (
                <div className="flex flex-wrap gap-1.5 mb-4">
                    {pains.map((p) => (
                        <span key={p} className="text-[11px] font-medium px-2 py-0.5 bg-bg-elevated text-ink-soft rounded-md border border-border truncate max-w-full">
                            {capitalizeFirst(p)}
                        </span>
                    ))}
                </div>
            )}

            <div className="flex items-center justify-between">
                <div className="flex items-center gap-3 text-[11px] font-medium text-ink-faint">
                    <span>{ageLabel(lead.created_at)}</span>
                    {typeof lead.num_comments === 'number' && (
                        <span className="inline-flex items-center gap-1">
                            <Icon icon="solar:chat-round-linear" width={12} /> {lead.num_comments}
                        </span>
                    )}
                    {lead.sent && (
                        <span className="inline-flex items-center gap-1 text-emerald-600">
                            <Icon icon="solar:check-circle-linear" width={12} /> sent
                        </span>
                    )}
                </div>
                <span className="text-[11px] font-semibold text-ink-soft bg-bg-elevated border border-border rounded-md px-2 py-0.5">
                    P{lead.priority ?? lead.signal_score * 10}
                </span>
            </div>

            <div className="absolute bottom-0 left-0 right-0 h-1 bg-border/60">
                <div
                    className={`h-full transition-all duration-500 ${lead.signal_score >= 7 ? 'bg-brand' : lead.signal_score >= 4 ? 'bg-amber-400' : 'bg-red-400'}`}
                    style={{ width: `${Math.min(100, lead.signal_score * 10)}%` }}
                ></div>
            </div>
        </button>
    )
}
