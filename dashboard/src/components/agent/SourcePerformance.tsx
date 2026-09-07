import React from 'react'

interface SourceStat {
    source: string
    total: number
    booked: number
    rate: string
}

interface SourcePerformanceProps {
    data: SourceStat[]
}

export const SourcePerformance: React.FC<SourcePerformanceProps> = ({ data }) => {
    // highlighted best row
    const bestSource = [...data].sort((a, b) => parseFloat(b.rate) - parseFloat(a.rate))[0]?.source

    return (
        <div className="overflow-hidden border border-border rounded-2xl bg-white shadow-card">
            <table className="w-full text-left border-collapse">
                <thead>
                    <tr className="bg-bg-elevated border-b border-border">
                        <th className="px-6 py-4 text-xs font-semibold text-ink-muted">Subreddit</th>
                        <th className="px-6 py-4 text-xs font-semibold text-ink-muted">Leads</th>
                        <th className="px-6 py-4 text-xs font-semibold text-ink-muted">Sent</th>
                        <th className="px-6 py-4 text-xs font-semibold text-ink-muted text-right">Send rate</th>
                    </tr>
                </thead>
                <tbody className="divide-y divide-border">
                    {data.map((row) => (
                        <tr key={row.source} className={`group hover:bg-bg-elevated transition-colors duration-200 ${row.source === bestSource ? 'relative' : ''}`}>
                            {row.source === bestSource && (
                                <div className="absolute left-0 top-0 bottom-0 w-1 bg-brand"></div>
                            )}
                            <td className="px-6 py-4 text-sm font-medium text-ink">{row.source}</td>
                            <td className="px-6 py-4 text-sm text-ink-muted">{row.total}</td>
                            <td className="px-6 py-4 text-sm text-ink-muted">{row.booked}</td>
                            <td className="px-6 py-4 text-right">
                                <span className={`text-sm font-semibold ${row.source === bestSource ? 'text-brand' : 'text-ink'}`}>
                                    {row.rate}%
                                </span>
                            </td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    )
}
