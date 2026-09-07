import React, { useState, useMemo } from 'react'
import type { Lead } from '../../types'
import { LeadCard } from './LeadCard'
import { Icon } from '@iconify/react'

interface LeadsListProps {
    leads: Lead[]
    selectedId: string | null
    onSelect: (id: string) => void
    mode?: 'all' | 'conversations'
    isLoading?: boolean
}

export const LeadsList: React.FC<LeadsListProps> = ({
    leads,
    selectedId,
    onSelect,
    mode = 'all'
}) => {
    const [search, setSearch] = useState('')
    const [tempFilter, setTempFilter] = useState('All')
    const [outcomeFilter, setOutcomeFilter] = useState('All')
    const [sortBy, setSortBy] = useState<'newest' | 'active' | 'signal'>('newest')

    const filteredLeads = useMemo(() => {
        return leads
            .filter(l => {
                const matchesSearch = `${l.first_name} ${l.last_name} ${l.company}`.toLowerCase().includes(search.toLowerCase())
                const matchesTemp = tempFilter === 'All' || l.temperature === tempFilter
                const matchesOutcome = outcomeFilter === 'All' || l.outcome === outcomeFilter
                return matchesSearch && matchesTemp && matchesOutcome
            })
            .sort((a, b) => {
                if (sortBy === 'newest') return new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
                if (sortBy === 'signal') return b.signal_score - a.signal_score
                return 0
            })
    }, [leads, search, tempFilter, outcomeFilter, sortBy])

    return (
        <div className="flex flex-col h-full bg-white">
            <div className="p-6 border-b border-border space-y-4">
                <div className="relative group">
                    <Icon icon="solar:magnifer-linear" width={18} className="absolute left-4 top-1/2 -translate-y-1/2 text-ink-faint group-focus-within:text-brand transition-colors" />
                    <input
                        type="text"
                        placeholder="Search posts or subreddits..."
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                        className="input-modern pl-11"
                    />
                </div>

                <div className="flex gap-3">
                    <select
                        value={tempFilter}
                        onChange={(e) => setTempFilter(e.target.value)}
                        className="input-modern flex-1 !py-2 text-xs font-medium cursor-pointer"
                    >
                        <option value="All">All Tiers</option>
                        <option value="Hot">Hot</option>
                        <option value="Warm">Warm</option>
                        <option value="Cold">Cold</option>
                    </select>
                    <select
                        value={outcomeFilter}
                        onChange={(e) => setOutcomeFilter(e.target.value)}
                        className="input-modern flex-1 !py-2 text-xs font-medium cursor-pointer"
                    >
                        <option value="All">All statuses</option>
                        <option value="In Progress">In pipeline</option>
                        <option value="Meeting Booked">Sent</option>
                    </select>
                </div>

                <div className="flex items-center justify-between text-xs font-medium text-ink-muted px-0.5">
                    <span className="flex items-center gap-2">
                        <Icon icon="solar:filter-linear" width={14} className="text-brand" />
                        {filteredLeads.length} leads
                    </span>
                    <div className="flex gap-4">
                        <button onClick={() => setSortBy('newest')} className={`transition-colors hover:text-brand ${sortBy === 'newest' ? 'text-brand font-semibold' : ''}`}>Newest</button>
                        <button onClick={() => setSortBy('signal')} className={`transition-colors hover:text-brand ${sortBy === 'signal' ? 'text-brand font-semibold' : ''}`}>Signal</button>
                    </div>
                </div>
            </div>

            <div className="flex-1 overflow-y-auto p-5 space-y-3 custom-scrollbar">
                {filteredLeads.map((lead, idx) => (
                    <div key={lead.id} className="animate-fade-up" style={{ animationDelay: `${idx * 40}ms` }}>
                        <LeadCard
                            lead={lead}
                            active={selectedId === lead.id}
                            onClick={() => onSelect(lead.id)}
                            showState={mode === 'conversations'}
                        />
                    </div>
                ))}
                {filteredLeads.length === 0 && (
                    <div className="py-32 text-center space-y-3">
                        <div className="w-12 h-12 bg-brand-muted rounded-full flex items-center justify-center mx-auto mb-2">
                            <Icon icon="solar:magnifer-linear" width={20} className="text-brand" />
                        </div>
                        <p className="text-sm text-ink-muted">No leads match your filters</p>
                    </div>
                )}
            </div>
        </div>
    )
}
