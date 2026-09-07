import React, { useState } from 'react'
import type { Lead } from '../types'
import { LeadsList } from '../components/leads/LeadsList'
import { LeadDetail } from '../components/leads/LeadDetail'
import { Icon } from '@iconify/react'

interface LeadsProps {
    leads: Lead[]
    isLoading?: boolean
    refetch: () => void
}

const Leads: React.FC<LeadsProps> = ({ leads, isLoading, refetch }) => {
    const [selectedLeadId, setSelectedLeadId] = useState<string | null>(leads[0]?.id || null)

    const selectedLead = leads.find(l => l.id === selectedLeadId)

    return (
        <div className="h-[calc(100vh-64px)] flex overflow-hidden lg:p-10 lg:gap-8 animate-fade-up bg-bg-base">
            <div className="w-full lg:w-[450px] flex-shrink-0 overflow-hidden flex flex-col border border-border bg-white rounded-2xl shadow-card">
                <div className="p-8 border-b border-border">
                    <div className="flex items-center gap-4">
                        <div className="w-12 h-12 rounded-xl bg-brand-muted flex items-center justify-center text-brand">
                            <Icon icon="solar:user-rounded-linear" width={26} />
                        </div>
                        <div>
                            <h1 className="text-2xl font-bold text-ink tracking-tight">
                                Leads
                            </h1>
                            <p className="text-xs text-ink-muted font-medium mt-0.5 flex items-center gap-2">
                                {leads.length} records online
                            </p>
                        </div>
                    </div>
                </div>
                <div className="flex-1 overflow-hidden relative">
                    {isLoading ? (
                         <div className="flex-1 flex flex-col items-center justify-center space-y-6 h-full">
                            <div className="w-10 h-10 border-[3px] border-brand/15 border-t-brand rounded-full animate-spin"></div>
                            <span className="text-xs text-ink-muted font-medium">Loading leads...</span>
                        </div>
                    ) : (
                        <div className="h-full">
                            <LeadsList
                                leads={leads}
                                selectedId={selectedLeadId}
                                onSelect={setSelectedLeadId}
                                isLoading={isLoading}
                            />
                        </div>
                    )}
                </div>
            </div>

            <div className="hidden lg:flex flex-1 glass-card-detail overflow-hidden relative">
                {selectedLead ? (
                    <div className="w-full h-full">
                        <LeadDetail
                            lead={selectedLead}
                            onClose={() => { }}
                            refetch={refetch}
                        />
                    </div>
                ) : (
                    <div className="absolute inset-0 flex flex-col items-center justify-center p-20 text-center space-y-8">
                        <div className="w-24 h-24 rounded-3xl bg-brand-muted flex items-center justify-center">
                            <Icon icon="solar:user-rounded-linear" width={44} className="text-brand" />
                        </div>
                        <div className="space-y-3">
                            <h3 className="text-xl font-semibold text-ink tracking-tight">No lead selected</h3>
                            <p className="text-sm text-ink-muted leading-relaxed max-w-[300px]">
                                Select a lead from the list to view its details and conversation.
                            </p>
                        </div>
                    </div>
                )}
            </div>
        </div>
    )
}

export default Leads
