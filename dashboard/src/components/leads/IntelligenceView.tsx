import React from 'react'
import type { Lead, ConversationState } from '../../types'
import { SignalScore } from '../ui/SignalScore'
import { Badge } from '../ui/Badge'
import { capitalizeFirst } from '../../lib/adapters'
import { Icon } from '@iconify/react'

interface IntelligenceViewProps {
    lead: Lead
    state: ConversationState | null
    onUpdate: () => void
}

const VERDICT_STYLE: Record<string, string> = {
    approved: 'bg-emerald-50 text-emerald-600 border-emerald-100',
    revise: 'bg-amber-50 text-amber-600 border-amber-100',
    rejected: 'bg-red-50 text-red-600 border-red-100',
    pending: 'bg-gray-100 text-gray-500 border-gray-200',
}

// Read-only qualification signals for a prospect. Editing (re-tier, re-run
// compliance) is Phase 2.
export const IntelligenceView: React.FC<IntelligenceViewProps> = ({ lead, state, onUpdate }) => {
    void onUpdate // editing is Phase 2
    const priority = lead.priority ?? lead.signal_score * 10
    const verdict = (lead.verdict || '').toLowerCase()

    return (
        <div className="space-y-6 animate-fade-up">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                {/* Scoring */}
                <section className="card p-8 relative overflow-hidden">
                    <div className="flex items-center justify-between mb-6">
                        <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-muted">Sendability</h3>
                        <SignalScore score={lead.signal_score} size="md" />
                    </div>
                    <div className="space-y-3">
                        <div className="flex justify-between items-center text-xs">
                            <span className="text-ink-muted">Priority</span>
                            <span className="font-semibold text-brand">{priority}/100</span>
                        </div>
                        <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
                            <div className="h-full bg-brand rounded-full transition-all duration-1000" style={{ width: `${Math.min(100, priority)}%` }} />
                        </div>
                    </div>
                    <div className="grid grid-cols-3 gap-3 mt-6">
                        <Stat label="Tier"><Badge variant="temperature" value={lead.temperature} /></Stat>
                        <Stat label="Comments">{lead.num_comments ?? '—'}</Stat>
                        <Stat label="Saturation">{lead.saturation || '—'}</Stat>
                    </div>
                </section>

                {/* Pipeline + compliance */}
                <section className="card p-8 space-y-6">
                    <div>
                        <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-muted mb-3">Pipeline stage</h3>
                        <Badge variant="state" value={state?.current_state || 'Discovery'} />
                    </div>
                    <div>
                        <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-muted mb-3">Compliance</h3>
                        {verdict ? (
                            <span className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold border ${VERDICT_STYLE[verdict] || VERDICT_STYLE.pending}`}>
                                <Icon icon="solar:shield-check-linear" width={14} /> {lead.verdict}
                            </span>
                        ) : (
                            <p className="text-xs text-ink-faint">Not yet drafted / checked</p>
                        )}
                    </div>
                    {lead.angle && (
                        <div>
                            <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-muted mb-2">Angle</h3>
                            <p className="text-sm text-ink leading-relaxed">{lead.angle}</p>
                        </div>
                    )}
                </section>
            </div>

            {/* Pain points — what the qualifier flagged */}
            <section className="card p-8">
                <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-muted mb-4">Detected pain points</h3>
                {lead.pains && lead.pains.length > 0 ? (
                    <div className="space-y-3">
                        {lead.pains.map((p) => (
                            <div key={p} className="flex items-center gap-3">
                                <span className="w-1.5 h-1.5 rounded-full bg-brand shrink-0"></span>
                                <span className="text-sm text-ink">{capitalizeFirst(p)}</span>
                            </div>
                        ))}
                    </div>
                ) : (
                    <p className="text-xs text-ink-faint">No specific pain points extracted for this post.</p>
                )}
            </section>
        </div>
    )
}

const Stat: React.FC<{ label: string; children: React.ReactNode }> = ({ label, children }) => (
    <div className="bg-bg-elevated border border-border rounded-xl p-3">
        <p className="text-[10px] font-medium text-ink-faint mb-1.5">{label}</p>
        <div className="text-sm font-semibold text-ink">{children}</div>
    </div>
)
