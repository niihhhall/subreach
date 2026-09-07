import React, { useMemo, useState } from 'react'
import type { ApiOverview, Lead } from '../types'
import { StatCard } from '../components/ui/StatCard'
import { LeadCard } from '../components/leads/LeadCard'
import { ActivityFeed } from '../components/agent/ActivityFeed'
import { useApi } from '../hooks/useApi'
import { isDemoMode } from '../lib/api'
import { MOCK_LEADS } from '../lib/mockData'
import { Icon } from '@iconify/react'
import { SkeletonCard } from '../components/ui/SkeletonCard'
import { LeadDetail } from '../components/leads/LeadDetail'

interface OverviewProps {
    leads: Lead[]
    isLoading?: boolean
}

const Overview: React.FC<OverviewProps> = ({ leads: propLeads, isLoading: propLoading }) => {
    const [selectedLeadId, setSelectedLeadId] = useState<string | null>(null)
    const { data: overview } = useApi<ApiOverview>('/overview')

    const leads = isDemoMode ? MOCK_LEADS : propLeads
    const isLoading = isDemoMode ? false : propLoading

    const stats = useMemo(() => {
        const total = overview?.total ?? leads.length
        const hot = overview?.tiers?.hot ?? leads.filter((l) => l.temperature === 'Hot').length
        const warm = overview?.tiers?.warm ?? leads.filter((l) => l.temperature === 'Warm').length
        const engageable = overview?.engageable ?? 0
        const sent = leads.filter((l) => l.sent).length
        const health = overview?.health?.score
        const karma = overview?.karma

        return [
            { label: 'Total Leads', value: total, icon: 'solar:users-group-rounded-linear', color: 'bg-brand-muted text-brand' },
            { label: 'Hot Tier', value: hot, icon: 'solar:fire-linear', color: 'bg-red-50 text-red-600', pulse: hot > 0 },
            { label: 'Warm Tier', value: warm, icon: 'solar:chat-round-dots-linear', color: 'bg-amber-50 text-amber-600' },
            { label: 'Engageable', value: engageable, icon: 'solar:target-linear', color: 'bg-violet-50 text-violet-600' },
            { label: 'Sent', value: sent, icon: 'solar:plain-linear', color: 'bg-emerald-50 text-emerald-600' },
            { label: 'Acct Karma', value: karma ?? (health != null ? `${health}` : '—'), icon: 'solar:bolt-linear', color: 'bg-sky-50 text-sky-600' },
        ]
    }, [overview, leads])

    const selectedLead = useMemo(() => leads.find((l) => l.id === selectedLeadId), [leads, selectedLeadId])

    return (
        <div className="p-8 space-y-12 animate-fade-up max-w-[1750px] mx-auto">
            {/* Header Stats Row */}
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-6">
                {isLoading
                    ? Array.from({ length: 6 }).map((_, i) => <SkeletonCard key={i} />)
                    : stats.map((s, i) => (
                          <StatCard key={i} label={s.label} value={s.value} icon={s.icon} accentColor={s.color} pulse={s.pulse} />
                      ))}
            </div>

            {/* Main Interactive Grid */}
            <div className="grid grid-cols-1 lg:grid-cols-4 gap-10 items-start">
                {/* Left: Lead Sidebar */}
                <div className="lg:col-span-1 space-y-6">
                    <div className="flex items-center justify-between px-2">
                        <h2 className="text-sm font-semibold tracking-tight text-ink inline-flex items-center gap-2.5 bg-white border border-border rounded-xl px-4 py-2 shadow-card">
                            <Icon icon="solar:graph-new-up-linear" width={18} className="text-brand" /> Recent Prospects
                        </h2>
                        <div className="flex items-center gap-2 bg-white border border-border rounded-xl px-4 py-2 shadow-card">
                            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></span>
                            <span className="text-xs font-medium text-ink-muted">Active</span>
                        </div>
                    </div>
                    <div className="space-y-4 max-h-[800px] overflow-y-auto pr-3 custom-scrollbar">
                        {isLoading
                            ? Array.from({ length: 5 }).map((_, i) => <SkeletonCard key={i} lines={2} height="h-24" />)
                            : leads.map((lead) => (
                                  <LeadCard
                                      key={lead.id}
                                      lead={lead}
                                      active={selectedLeadId === lead.id}
                                      onClick={() => setSelectedLeadId(lead.id)}
                                      variant="compact"
                                  />
                              ))}
                    </div>
                </div>

                {/* Right: Detailed View or Intelligence Placeholder */}
                <div className="lg:col-span-3 card overflow-hidden flex flex-col relative min-h-[600px]">
                    {selectedLead ? (
                        <LeadDetail lead={selectedLead} onClose={() => setSelectedLeadId(null)} refetch={() => {}} />
                    ) : (
                        <div className="m-auto flex flex-col items-center text-center p-12 max-w-xl">
                            <div className="relative mb-10">
                                <div className="relative w-24 h-24 bg-brand-muted border border-brand/20 flex items-center justify-center rotate-6 transform transition-all hover:rotate-0 hover:scale-105 duration-700 shadow-card rounded-2xl">
                                    <Icon icon="solar:cpu-bolt-linear" width={44} className="text-brand" />
                                </div>
                                <div className="absolute -bottom-3 -right-3 w-11 h-11 bg-white border border-border shadow-card flex items-center justify-center -rotate-12 rounded-xl">
                                    <Icon icon="solar:wi-fi-router-bold" width={20} className="text-brand" />
                                </div>
                            </div>
                            <h3 className="text-3xl font-bold text-ink tracking-tight">
                                Prospect <span className="text-brand">Detail</span>
                            </h3>
                            <p className="text-ink-muted text-sm mt-4 leading-relaxed max-w-md mx-auto font-medium">
                                Select a lead from the registry to inspect the discovered post, drafted reply, and qualification signals.
                            </p>

                            <div className="grid grid-cols-2 gap-6 mt-10 w-full text-left">
                                <div className="p-5 bg-bg-elevated border border-border rounded-xl transition-all group hover:border-brand/30">
                                    <p className="text-xs font-semibold text-brand tracking-tight mb-2 flex items-center gap-2">
                                        <Icon icon="solar:bolt-linear" width={16} className="group-hover:rotate-12 transition-transform" /> Discovery
                                    </p>
                                    <p className="text-xs text-ink-muted leading-relaxed">Live Reddit posts matched to your ICP across target subreddits.</p>
                                </div>
                                <div className="p-5 bg-bg-elevated border border-border rounded-xl transition-all group hover:border-brand/30">
                                    <p className="text-xs font-semibold text-violet-600 tracking-tight mb-2 flex items-center gap-2">
                                        <Icon icon="solar:trending-up-linear" width={16} className="group-hover:scale-110 transition-transform" /> Qualification
                                    </p>
                                    <p className="text-xs text-ink-muted leading-relaxed">Fit + intent scoring, triage tier, and a compliance-checked draft.</p>
                                </div>
                            </div>
                        </div>
                    )}
                </div>
            </div>

            {/* Bottom Row: System Pulse */}
            <div className="pt-8 border-t border-border">
                <div className="flex items-center justify-between mb-8 px-2">
                    <h2 className="text-sm font-semibold tracking-tight text-ink inline-flex items-center gap-2.5 bg-white border border-border rounded-xl px-4 py-2 shadow-card">
                        <Icon icon="solar:activity-linear" width={18} className="text-brand" /> Activity Feed
                    </h2>
                    <span className="text-xs text-ink-faint bg-white border border-border rounded-xl px-4 py-2 shadow-card">comments · dms · handoffs</span>
                </div>
                <ActivityFeed />
            </div>
        </div>
    )
}

export default Overview
