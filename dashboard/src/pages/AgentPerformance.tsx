import React, { useMemo } from 'react'
import { Icon } from '@iconify/react'
import type { ApiHealth, ApiOverview } from '../types'
import { useApi } from '../hooks/useApi'
import { StatCard } from '../components/ui/StatCard'
import { StateDistribution } from '../components/agent/StateDistribution'
import { SourcePerformance } from '../components/agent/SourcePerformance'

// Nice labels for pipeline stages coming back in overview.funnel.
const STAGE_LABELS: Record<string, string> = {
    discovered: 'Discovered',
    qualified: 'Qualified',
    researched: 'Researched',
    drafted: 'Drafted',
    approved: 'Approved',
    needs_revision: 'Needs Revision',
    sent: 'Sent',
    dm_sent: 'DM Sent',
    handed_off: 'Handed Off',
    disqualified: 'Disqualified',
    rejected: 'Rejected',
}

const AgentPerformance: React.FC = () => {
    const { data: overview } = useApi<ApiOverview>('/overview')
    const { data: health } = useApi<ApiHealth>('/health')

    const analytics = useMemo(() => {
        const funnel = overview?.funnel || {}
        const totalStages = Object.values(funnel).reduce((s, n) => s + n, 0)
        const distribution = Object.entries(funnel)
            .map(([stage, count]) => ({
                name: STAGE_LABELS[stage] || stage,
                count,
                percent: totalStages > 0 ? Math.round((count / totalStages) * 100) : 0,
            }))
            .sort((a, b) => b.count - a.count)

        const sourcePerformance = (overview?.subreddits || [])
            .map((s) => ({
                source: `r/${s.subreddit}`,
                total: s.leads,
                booked: s.sent,
                rate: s.leads > 0 ? Math.round((s.sent / s.leads) * 100).toString() : '0',
            }))
            .sort((a, b) => b.total - a.total)

        return { distribution, sourcePerformance }
    }, [overview])

    const stats = [
        { label: 'Total Leads', value: overview?.total ?? 0, icon: 'solar:users-group-rounded-linear', color: 'bg-brand-muted text-brand' },
        { label: 'Engageable', value: overview?.engageable ?? 0, icon: 'solar:target-linear', color: 'bg-emerald-50 text-emerald-600' },
        { label: 'Account Karma', value: overview?.karma ?? health?.karma_trend?.slice(-1)[0]?.total_karma ?? '—', icon: 'solar:bolt-linear', color: 'bg-amber-50 text-amber-600' },
        { label: 'Health Score', value: health?.score != null ? `${health.score}` : overview?.health?.score != null ? `${overview.health.score}` : '—', icon: 'solar:health-linear', color: 'bg-brand-muted text-brand' },
    ]

    return (
        <div className="p-8 space-y-10 animate-fade-up h-full overflow-y-auto pb-20 max-w-[1600px] mx-auto">
            <div className="flex items-center justify-between px-2">
                <div>
                    <h2 className="text-sm font-semibold text-ink-soft flex items-center gap-2">
                        <Icon icon="solar:chart-square-linear" width={18} className="text-brand" /> Performance Overview
                    </h2>
                    <p className="text-xs text-ink-muted mt-1">Pipeline funnel, account health, and per-subreddit yield</p>
                </div>
                <div className="flex items-center gap-6">
                    <div
                        className={`flex items-center gap-2 px-4 py-2 rounded-full border ${
                            health?.breaker_open ? 'bg-red-50 border-red-100' : 'bg-emerald-50 border-emerald-100'
                        }`}
                    >
                        <span className={`w-2 h-2 rounded-full ${health?.breaker_open ? 'bg-red-500' : 'bg-emerald-500 animate-pulse'}`}></span>
                        <span className={`text-xs font-semibold ${health?.breaker_open ? 'text-red-600' : 'text-emerald-600'}`}>
                            {health?.breaker_open ? 'Breaker Open' : 'Core Synchronized'}
                        </span>
                    </div>
                </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
                {stats.map((s, i) => (
                    <StatCard key={i} label={s.label} value={s.value} icon={s.icon} accentColor={s.color} />
                ))}
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
                <div className="card p-8 space-y-8">
                    <h2 className="text-sm font-semibold text-ink mb-2">Pipeline Distribution</h2>
                    {analytics.distribution.length > 0 ? (
                        <StateDistribution data={analytics.distribution} />
                    ) : (
                        <EmptyChart />
                    )}
                </div>
                <div className="card p-8 space-y-8">
                    <h2 className="text-sm font-semibold text-ink mb-2">Subreddit Performance</h2>
                    {analytics.sourcePerformance.length > 0 ? <SourcePerformance data={analytics.sourcePerformance} /> : <EmptyChart />}
                </div>
            </div>
        </div>
    )
}

const EmptyChart: React.FC = () => (
    <div className="flex flex-col items-center justify-center py-20 text-center space-y-4">
        <div className="w-14 h-14 rounded-full bg-gray-100 flex items-center justify-center text-gray-400">
            <Icon icon="solar:chart-square-linear" width={28} />
        </div>
        <p className="text-xs text-ink-muted font-medium">Awaiting registry data</p>
    </div>
)

export default AgentPerformance
