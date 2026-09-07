import React, { useMemo } from 'react'
import { Icon } from '@iconify/react'
import type { ApiScout } from '../types'
import { useApi } from '../hooks/useApi'
import { flattenScout } from '../lib/adapters'

// Repurposed for reddit-outreach: the "Training" tab now surfaces the Subreddit
// Scout output (/api/scout) — the verticals and subreddits the scout discovered
// and validated against live feeds. Read-only in Phase 1 (curation is Phase 2).
const Scout: React.FC = () => {
    const { data, isLoading, error } = useApi<ApiScout>('/scout')

    const rows = useMemo(() => flattenScout(data?.verticals || {}), [data])
    const verticals = useMemo(() => Object.keys(data?.verticals || {}), [data])

    return (
        <div className="p-10 space-y-8 animate-fade-up max-w-[1600px] mx-auto pb-20">
            <div className="flex flex-col md:flex-row md:items-end justify-between gap-6 pb-6 border-b border-border">
                <div>
                    <h1 className="text-3xl font-bold text-ink tracking-tight">
                        Subreddit <span className="text-brand">Scout</span>
                    </h1>
                    <p className="text-sm text-ink-muted mt-2">Discovered verticals and validated target subreddits</p>
                </div>
            </div>

            {error && (
                <div className="flex items-center gap-3 px-5 py-4 bg-red-50 border border-red-100 rounded-2xl text-xs font-medium text-red-600">
                    <Icon icon="solar:danger-triangle-linear" width={18} className="shrink-0" />
                    Backend unreachable — check the API base and client token.
                </div>
            )}

            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                <div className="card p-6 flex items-center gap-5">
                    <div className="w-12 h-12 rounded-xl bg-brand-muted flex items-center justify-center text-brand shrink-0">
                        <Icon icon="solar:layers-linear" width={24} />
                    </div>
                    <div>
                        <p className="text-xs font-medium text-ink-muted">Verticals</p>
                        <h3 className="text-2xl font-bold text-ink tracking-tight mt-0.5">{verticals.length}</h3>
                    </div>
                </div>
                <div className="card p-6 flex items-center gap-5">
                    <div className="w-12 h-12 rounded-xl bg-amber-50 flex items-center justify-center text-amber-600 shrink-0">
                        <Icon icon="solar:hashtag-linear" width={24} />
                    </div>
                    <div>
                        <p className="text-xs font-medium text-ink-muted">Subreddits Found</p>
                        <h3 className="text-2xl font-bold text-ink tracking-tight mt-0.5">{data?.total ?? 0}</h3>
                    </div>
                </div>
                <div className="card p-6 flex items-center gap-5">
                    <div className="w-12 h-12 rounded-xl bg-emerald-50 flex items-center justify-center text-emerald-600 shrink-0">
                        <Icon icon="solar:check-circle-linear" width={24} />
                    </div>
                    <div>
                        <p className="text-xs font-medium text-ink-muted">Active (validated)</p>
                        <h3 className="text-2xl font-bold text-ink tracking-tight mt-0.5">{data?.active ?? 0}</h3>
                    </div>
                </div>
            </div>

            <div className="card overflow-hidden">
                <div className="p-8 border-b border-border bg-bg-elevated/50 flex items-center gap-4">
                    <div className="w-10 h-10 rounded-xl bg-brand-muted flex items-center justify-center text-brand">
                        <Icon icon="solar:magnifer-linear" width={22} />
                    </div>
                    <div>
                        <h2 className="text-lg font-bold text-ink tracking-tight">Discovered Subreddits</h2>
                        <p className="text-xs text-ink-muted mt-0.5">Ranked by relevance, grouped by vertical</p>
                    </div>
                </div>

                <div className="p-8">
                    {isLoading ? (
                        <div className="flex flex-col items-center justify-center py-32 space-y-6">
                            <div className="w-14 h-14 border-4 border-gray-100 border-t-brand rounded-full animate-spin"></div>
                            <p className="text-ink-muted text-xs font-medium animate-pulse">Loading scout data...</p>
                        </div>
                    ) : rows.length === 0 ? (
                        <div className="py-24 text-center space-y-4">
                            <div className="w-14 h-14 rounded-full bg-gray-100 flex items-center justify-center text-gray-400 mx-auto">
                                <Icon icon="solar:magnifer-linear" width={28} />
                            </div>
                            <p className="text-xs text-ink-muted font-medium">No scouted subreddits yet — run the scout loop</p>
                        </div>
                    ) : (
                        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                            {rows.map((row, i) => (
                                <div
                                    key={`${row.vertical}-${row.subreddit}-${i}`}
                                    className="p-5 card hover:shadow-lift transition-all animate-fade-up"
                                    style={{ animationDelay: `${i * 20}ms` }}
                                >
                                    <div className="flex items-center justify-between mb-3">
                                        <h3 className="font-semibold text-ink tracking-tight">r/{row.subreddit}</h3>
                                        <span
                                            className={`px-2.5 py-0.5 rounded-full text-[11px] font-semibold border ${
                                                row.active
                                                    ? 'bg-emerald-50 text-emerald-600 border-emerald-100'
                                                    : 'bg-gray-100 text-gray-500 border-gray-200'
                                            }`}
                                        >
                                            {row.active ? 'active' : 'inactive'}
                                        </span>
                                    </div>
                                    <p className="text-[11px] font-medium text-ink-faint uppercase tracking-wide mb-3">{row.vertical}</p>
                                    <div className="flex items-center justify-between text-xs text-ink-muted">
                                        <span className="flex items-center gap-1.5">
                                            <Icon icon="solar:graph-up-linear" width={14} className="text-brand" />
                                            relevance {Math.round((row.relevance || 0) * 100) / 100}
                                        </span>
                                        <span>{row.sample_count} samples</span>
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            </div>
        </div>
    )
}

export default Scout
