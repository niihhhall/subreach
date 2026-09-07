import React, { useMemo, useState } from 'react'
import type { ApiOutreach, Booking, Lead } from '../types'
import { useApi } from '../hooks/useApi'
import { activityToBooking } from '../lib/adapters'
import { StatCard } from '../components/ui/StatCard'
import { BookingsTable } from '../components/bookings/BookingsTable'
import { LeadDetail } from '../components/leads/LeadDetail'
import { Icon } from '@iconify/react'

interface HandoffsProps {
    leads: Lead[]
    isLoading?: boolean
}

// Leads handed off to Markeye (the downstream WhatsApp SDR) plus leads pending
// handoff, from /api/outreach.
const Handoffs: React.FC<HandoffsProps> = ({ leads }) => {
    const { data, isLoading } = useApi<ApiOutreach>('/outreach')
    const [selectedLead, setSelectedLead] = useState<Lead | null>(null)

    const bookings = useMemo<(Booking & { lead?: Lead })[]>(() => {
        const handoffs = (data?.handoffs || []).map(activityToBooking)
        // enrich with full lead where we have it locally
        return handoffs.map((b) => ({
            ...b,
            lead: leads.find((l) => l.id === b.lead_id) || b.lead,
        }))
    }, [data, leads])

    const stats = useMemo(() => {
        const counts = data?.counts
        const handed = counts?.handed_off ?? bookings.length
        const pending = counts?.pending ?? (data?.pending?.length || 0)
        const dmSent = counts?.dm_sent ?? 0
        const total = handed + pending

        return [
            { label: 'Handed Off', value: handed, icon: 'solar:check-circle-linear', color: 'bg-emerald-50 text-emerald-600' },
            { label: 'Pending Handoff', value: pending, icon: 'solar:clock-circle-linear', color: 'bg-amber-50 text-amber-600' },
            { label: 'DMs Sent', value: dmSent, icon: 'solar:plain-linear', color: 'bg-sky-50 text-sky-600' },
            { label: 'Total Pipeline', value: total, icon: 'solar:users-group-rounded-linear', color: 'bg-brand-muted text-brand' },
        ]
    }, [data, bookings])

    return (
        <div className="p-8 space-y-10 animate-fade-up h-full overflow-y-auto pb-20 max-w-[1700px] mx-auto">
            <div className="flex items-center justify-between px-2">
                <div>
                    <h1 className="text-3xl font-bold tracking-tight text-ink">
                        Lead <span className="text-brand">Handoffs</span>
                    </h1>
                    <p className="text-xs text-ink-muted mt-1">Leads routed to Markeye for WhatsApp qualification</p>
                </div>
                <div className="flex items-center gap-6">
                    <div className="flex items-center gap-2 px-4 py-2 card rounded-full">
                        <div className="w-2 h-2 rounded-full bg-emerald-500"></div>
                        <span className="text-xs font-semibold text-emerald-600">Sync Active</span>
                    </div>
                </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
                {stats.map((s, i) => (
                    <StatCard key={i} label={s.label} value={s.value} icon={s.icon} accentColor={s.color} />
                ))}
            </div>

            <div className="card overflow-hidden relative">
                <div className="p-8 border-b border-border flex items-center justify-between bg-bg-elevated/50">
                    <div className="flex items-center gap-4">
                        <div className="w-10 h-10 rounded-xl bg-brand-muted flex items-center justify-center text-brand">
                            <Icon icon="solar:transfer-horizontal-linear" width={22} />
                        </div>
                        <div>
                            <h2 className="text-lg font-bold text-ink tracking-tight">Handoff Log</h2>
                            <p className="text-xs text-ink-muted mt-0.5">Signed webhook events delivered to Markeye</p>
                        </div>
                    </div>
                </div>

                <div className="p-2">
                    <BookingsTable bookings={bookings} isLoading={isLoading} onViewLead={setSelectedLead} />
                </div>
            </div>

            {selectedLead && (
                <div className="fixed inset-0 z-[100] flex justify-end">
                    <div className="absolute inset-0 bg-ink/20 backdrop-blur-sm animate-in fade-in duration-500" onClick={() => setSelectedLead(null)} />
                    <div className="relative w-full max-w-2xl bg-bg-card border-l border-border h-full animate-in slide-in-from-right duration-700 shadow-lift">
                        <div className="h-full overflow-hidden">
                            <LeadDetail lead={selectedLead} onClose={() => setSelectedLead(null)} refetch={() => {}} />
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}

export default Handoffs
