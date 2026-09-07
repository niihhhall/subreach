import React from 'react'
import { Icon } from '@iconify/react'

interface StatCardProps {
    label: string
    value: string | number
    icon: string
    accentColor?: string
    pulse?: boolean
}

export const StatCard: React.FC<StatCardProps> = ({ label, value, icon, accentColor, pulse }) => {
    return (
        <div className="card p-5 group hover:border-brand/30 hover:shadow-lift transition-all duration-300 animate-fade-up">
            <div className="flex items-start justify-between mb-4">
                <div className={`w-10 h-10 rounded-xl flex items-center justify-center ${accentColor || 'bg-brand-muted text-brand'}`}>
                    <Icon icon={icon} width={20} />
                </div>
                {pulse && <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse-dot"></span>}
            </div>
            <p className="text-ink-muted text-xs font-medium mb-1">{label}</p>
            <h3 className="text-2xl font-bold text-ink tracking-tight">{value}</h3>
        </div>
    )
}
