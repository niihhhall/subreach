import React from 'react'

type BadgeVariant = 'temperature' | 'outcome' | 'source' | 'state' | 'default'

interface BadgeProps {
    label?: string
    variant?: BadgeVariant
    value?: string
}

const colorMaps: Record<string, string> = {
    // Temperature
    'Hot': 'bg-red-50 text-red-600 border-red-100',
    'Warm': 'bg-amber-50 text-amber-600 border-amber-100',
    'Cold': 'bg-sky-50 text-sky-600 border-sky-100',

    // Outcome
    'In Progress': 'bg-sky-50 text-sky-600 border-sky-100',
    'Meeting Booked': 'bg-emerald-50 text-emerald-600 border-emerald-100',
    'Not Interested': 'bg-orange-50 text-orange-600 border-orange-100',
    'Disqualified': 'bg-gray-100 text-gray-500 border-gray-200',

    // Source
    'Google': 'bg-blue-50 text-blue-600 border-blue-100',
    'Meta': 'bg-purple-50 text-purple-600 border-purple-100',
    'Referral': 'bg-brand-muted text-brand border-brand/15',
    'Other': 'bg-gray-100 text-gray-500 border-gray-200',

    // Conversation State
    'Opening': 'bg-gray-100 text-gray-500 border-gray-200',
    'Discovery': 'bg-sky-50 text-sky-600 border-sky-100',
    'Qualification': 'bg-amber-50 text-amber-600 border-amber-100',
    'Intent Building': 'bg-indigo-50 text-indigo-600 border-indigo-100',
    'Booking Push': 'bg-brand-muted text-brand border-brand/15',
    'Awaiting': 'bg-yellow-50 text-yellow-600 border-yellow-100',
    'Confirmed': 'bg-emerald-50 text-emerald-600 border-emerald-100',
    'Escalation': 'bg-red-50 text-red-600 border-red-100',
}

export const Badge: React.FC<BadgeProps> = ({ label, variant = 'default', value }) => {
    const displayLabel = value || label || ''
    const colorClass = (colorMaps as Record<string, string>)[displayLabel] || (variant === 'default' ? 'bg-bg-elevated text-ink-muted border-border' : 'bg-white text-ink-faint border-border')

    return (
        <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-semibold tracking-wide border whitespace-nowrap ${colorClass}`}>
            {displayLabel}
        </span>
    )
}
