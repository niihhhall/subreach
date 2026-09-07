import React from 'react'
import type { Lead } from '../../types'

interface LeadProfileProps {
    lead: Lead
}

const DetailRow = ({ label, value }: { label: string, value: string }) => (
    <div className="space-y-1">
        <span className="text-[11px] text-ink-faint font-medium">{label}</span>
        <p className="text-sm font-medium text-ink">{value || '—'}</p>
    </div>
)

export const LeadProfile: React.FC<LeadProfileProps> = ({ lead }) => {
    return (
        <div className="space-y-10 animate-in fade-in slide-in-from-bottom-2 duration-500">
            <div className="grid grid-cols-2 gap-y-8 gap-x-12">
                <DetailRow label="First Name" value={lead.first_name} />
                <DetailRow label="Last Name" value={lead.last_name} />
                <DetailRow label="Company" value={lead.company} />
                <DetailRow label="Industry" value={lead.industry} />
                <DetailRow label="Direct Phone" value={lead.phone} />
                <DetailRow label="Email Address" value={lead.email} />
                <DetailRow label="Source" value={lead.lead_source} />
                <DetailRow label="Created At" value={new Date(lead.created_at).toLocaleDateString()} />
            </div>

            <div className="space-y-3 pt-6 border-t border-border">
                <h4 className="text-xs font-semibold text-ink-muted">Initial Inquiry Message</h4>
                <div className="p-5 bg-brand-muted rounded-xl border-l-4 border-brand text-sm text-ink leading-relaxed">
                    "{lead.form_message}"
                </div>
            </div>
        </div>
    )
}
