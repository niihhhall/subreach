import React from 'react'
import { Icon } from '@iconify/react'

interface Option {
    id: string
    label: string
    icon?: string
}

interface SegmentedControlProps {
    options: (string | Option)[]
    activeId: string
    onChange: (id: string) => void
}

export const SegmentedControl: React.FC<SegmentedControlProps> = ({ options, activeId, onChange }) => {
    return (
        <div className="inline-flex p-1 bg-bg-elevated border border-border rounded-xl">
            {options.map((option) => {
                const id = typeof option === 'string' ? option : option.id
                const label = typeof option === 'string' ? option : option.label
                const iconName = typeof option === 'string' ? null : option.icon
                const isActive = activeId === id

                return (
                    <button
                        key={id}
                        onClick={() => onChange(id)}
                        className={`px-4 py-1.5 text-xs font-semibold rounded-lg transition-all inline-flex items-center justify-center gap-2 ${isActive
                            ? 'bg-white text-brand shadow-card border border-border'
                            : 'text-ink-muted hover:text-ink'
                            }`}
                    >
                        {iconName && <Icon icon={iconName} width={14} />}
                        {label}
                    </button>
                )
            })}
        </div>
    )
}
