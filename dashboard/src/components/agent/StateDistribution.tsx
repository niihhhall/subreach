import React from 'react'
import { Badge } from '../ui/Badge'

interface StateCount {
    name: string
    count: number
    percent: number
}

interface StateDistributionProps {
    data: StateCount[]
}

export const StateDistribution: React.FC<StateDistributionProps> = ({ data }) => {
    return (
        <div className="space-y-6">
            <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold tracking-tight text-ink">State Distribution</h3>
                <span className="text-xs text-ink-muted">Vector Distribution</span>
            </div>

            <div className="space-y-5">
                {data.map((item, idx) => (
                    <div key={item.name} className="space-y-2.5 animate-fade-up" style={{ animationDelay: `${idx * 50}ms` }}>
                        <div className="flex justify-between items-center text-xs">
                            <div className="scale-90 origin-left">
                                <Badge variant="state" value={item.name as any} label="State" />
                            </div>
                            <div className="flex gap-3 font-semibold tracking-tight">
                                <span className="text-ink-muted bg-gray-100 px-2 py-0.5 rounded-md">{item.count}</span>
                                <span className="text-brand pt-0.5">{item.percent}%</span>
                            </div>
                        </div>
                        <div className="h-1.5 w-full bg-gray-100 rounded-full overflow-hidden">
                            <div
                                className="h-full bg-brand rounded-full transition-all duration-1000"
                                style={{ width: `${item.percent}%` }}
                            ></div>
                        </div>
                    </div>
                ))}
            </div>
        </div>
    )
}
