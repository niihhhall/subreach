import React, { useMemo } from 'react'
import { Icon } from '@iconify/react'
import type { ApiSwarmAccount } from '../types'
import { useApi } from '../hooks/useApi'
import { StatCard } from '../components/ui/StatCard'

// Reddit accounts in the warm-up swarm (/api/swarm). Each account posts a few
// genuinely helpful, non-promotional comments per day in its own subreddits to
// build karma before outreach. Read-only in Phase 1.
const Accounts: React.FC = () => {
    const { data, isLoading } = useApi<{ accounts: ApiSwarmAccount[]; warnings: string[] }>('/swarm')
    const accounts = useMemo(() => data?.accounts || [], [data])
    const warnings = data?.warnings || []

    const stats = useMemo(() => {
        const total = accounts.length
        const awake = accounts.filter((a) => a.awake).length
        const breakers = accounts.filter((a) => a.breaker_open).length
        const karma = accounts.reduce((s, a) => s + (a.karma || 0), 0)
        return [
            { label: 'Accounts', value: total, icon: 'solar:users-group-two-rounded-linear', color: 'bg-brand-muted text-brand' },
            { label: 'Awake Now', value: awake, icon: 'solar:sun-linear', color: 'bg-emerald-50 text-emerald-600', pulse: awake > 0 },
            { label: 'Breakers Open', value: breakers, icon: 'solar:shield-warning-linear', color: breakers > 0 ? 'bg-red-50 text-red-600' : 'bg-gray-100 text-gray-500' },
            { label: 'Total Karma', value: karma || '—', icon: 'solar:bolt-linear', color: 'bg-amber-50 text-amber-600' },
        ]
    }, [accounts])

    return (
        <div className="p-8 space-y-10 animate-fade-up max-w-[1700px] mx-auto pb-20">
            <div className="flex items-center justify-between px-2">
                <div>
                    <h1 className="text-3xl font-bold text-ink tracking-tight">
                        Warm-up <span className="text-brand">Swarm</span>
                    </h1>
                    <p className="text-sm text-ink-muted mt-2">Reddit accounts building karma before outreach</p>
                </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
                {stats.map((s, i) => (
                    <StatCard key={i} label={s.label} value={s.value} icon={s.icon} accentColor={s.color} pulse={s.pulse} />
                ))}
            </div>

            {warnings.length > 0 && (
                <div className="card p-5 border-amber-200 bg-amber-50/40 space-y-2">
                    <div className="flex items-center gap-2 text-amber-700 text-xs font-semibold">
                        <Icon icon="solar:danger-triangle-linear" width={16} /> Roster warnings
                    </div>
                    {warnings.map((w, i) => (
                        <p key={i} className="text-xs text-ink-muted">{w}</p>
                    ))}
                </div>
            )}

            {isLoading ? (
                <div className="py-24 text-center">
                    <Icon icon="solar:refresh-linear" width={32} className="text-brand animate-spin mx-auto mb-4" />
                    <p className="text-xs font-medium text-ink-muted">Loading accounts...</p>
                </div>
            ) : accounts.length === 0 ? (
                <div className="card py-24 text-center space-y-4">
                    <div className="w-14 h-14 rounded-full bg-gray-100 flex items-center justify-center text-gray-400 mx-auto">
                        <Icon icon="solar:users-group-two-rounded-linear" width={28} />
                    </div>
                    <div className="space-y-1">
                        <h3 className="text-sm font-semibold text-ink">No swarm accounts configured</h3>
                        <p className="text-xs text-ink-muted">Add a roster in <code className="px-1 py-0.5 bg-bg-elevated rounded">accounts.yaml</code> or the SWARM_ACCOUNTS env var.</p>
                    </div>
                </div>
            ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                    {accounts.map((a) => {
                        const status = a.breaker_open ? 'breaker open' : a.has_key ? (a.awake ? 'active' : 'sleeping') : 'no key'
                        const statusColor = a.breaker_open
                            ? 'bg-red-50 text-red-600 border-red-100'
                            : !a.has_key
                              ? 'bg-gray-100 text-gray-500 border-gray-200'
                              : a.awake
                                ? 'bg-emerald-50 text-emerald-600 border-emerald-100'
                                : 'bg-sky-50 text-sky-600 border-sky-100'
                        const pct = a.cap > 0 ? Math.min(100, Math.round((a.today / a.cap) * 100)) : 0
                        return (
                            <div key={a.label} className="card p-7 hover:border-brand/30 hover:shadow-lift transition-all duration-300">
                                <div className="flex justify-between items-start mb-6">
                                    <div className="space-y-1.5 min-w-0">
                                        <h3 className="text-lg font-bold text-ink tracking-tight truncate">{a.label}</h3>
                                        {a.persona && (
                                            <div className="flex items-center gap-2">
                                                <Icon icon="solar:user-id-linear" width={14} className="text-ink-faint" />
                                                <p className="text-xs text-ink-muted capitalize">{a.persona}</p>
                                            </div>
                                        )}
                                    </div>
                                    <span className={`px-3 py-1 rounded-full text-[11px] font-semibold border ${statusColor}`}>{status}</span>
                                </div>

                                <div className="flex flex-wrap gap-1.5 mb-6 min-h-[26px]">
                                    {(a.subreddits || []).slice(0, 6).map((s) => (
                                        <span key={s} className="text-[11px] font-medium px-2 py-0.5 bg-bg-elevated text-ink-soft rounded-md border border-border">
                                            r/{s}
                                        </span>
                                    ))}
                                    {(a.subreddits || []).length > 6 && (
                                        <span className="text-[11px] text-ink-faint px-1 py-0.5">+{a.subreddits.length - 6}</span>
                                    )}
                                </div>

                                <div className="space-y-3 pt-4 border-t border-border">
                                    <div className="flex items-center justify-between text-xs">
                                        <span className="text-ink-muted">Sends today</span>
                                        <span className="text-ink font-semibold">{a.today} / {a.cap}</span>
                                    </div>
                                    <div className="h-1.5 w-full bg-gray-100 rounded-full overflow-hidden">
                                        <div className="h-full bg-brand rounded-full transition-all duration-700" style={{ width: `${pct}%` }} />
                                    </div>
                                    <div className="flex items-center justify-between text-xs pt-1">
                                        <span className="text-ink-muted flex items-center gap-1.5">
                                            <Icon icon="solar:bolt-linear" width={13} className="text-amber-500" /> Karma
                                        </span>
                                        <span className="text-ink font-semibold">{a.karma ?? '—'}</span>
                                    </div>
                                    <div className="flex items-center justify-between text-xs">
                                        <span className="text-ink-muted">Active hours</span>
                                        <span className="text-ink-soft">{a.active_hours} (tz{a.tz_offset >= 0 ? '+' : ''}{a.tz_offset})</span>
                                    </div>
                                </div>
                            </div>
                        )
                    })}
                </div>
            )}
        </div>
    )
}

export default Accounts
