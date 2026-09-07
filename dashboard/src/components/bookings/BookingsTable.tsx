import React from 'react'
import type { Booking, Lead } from '../../types'
import { Badge } from '../ui/Badge'
import { Icon } from '@iconify/react'

interface BookingsTableProps {
    bookings: (Booking & { lead?: Lead })[]
    onViewLead: (lead: Lead) => void
    isLoading?: boolean
}

export const BookingsTable: React.FC<BookingsTableProps> = ({ bookings, onViewLead }) => {
    return (
        <div className="overflow-hidden rounded-2xl bg-bg-card">
            <div className="overflow-x-auto custom-scrollbar">
                <table className="w-full text-left border-collapse">
                    <thead>
                        <tr className="bg-bg-elevated border-b border-border">
                            <th className="px-8 py-4 text-xs font-semibold uppercase tracking-wide text-ink-muted">Author</th>
                            <th className="px-8 py-4 text-xs font-semibold uppercase tracking-wide text-ink-muted">Subreddit</th>
                            <th className="px-8 py-4 text-xs font-semibold uppercase tracking-wide text-ink-muted">Handed off</th>
                            <th className="px-8 py-4 text-xs font-semibold uppercase tracking-wide text-ink-muted text-right">Ref</th>
                            <th className="px-8 py-4 text-xs font-semibold uppercase tracking-wide text-ink-muted text-right">Status</th>
                            <th className="px-8 py-4 text-xs font-semibold uppercase tracking-wide text-ink-muted text-right">Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        {bookings.map((booking) => (
                            <tr key={booking.id} className="group hover:bg-brand-muted/40 border-b border-border last:border-0 transition-colors duration-200">
                                <td className="px-8 py-5">
                                    <div className="flex items-center gap-4">
                                        <div className="w-10 h-10 rounded-xl bg-brand-muted flex items-center justify-center text-sm font-bold text-brand">
                                            {booking.lead?.first_name?.[0]}{booking.lead?.last_name?.[0]}
                                        </div>
                                        <div>
                                            <p className="text-sm font-semibold text-ink tracking-tight">{booking.lead?.first_name} {booking.lead?.last_name}</p>
                                            <p className="text-[11px] text-ink-muted mt-0.5">{booking.lead?.lead_source}</p>
                                        </div>
                                    </div>
                                </td>
                                <td className="px-8 py-5">
                                    <p className="text-sm font-medium text-ink">{booking.lead?.company || '—'}</p>
                                    <p className="text-[11px] text-ink-muted mt-0.5">{booking.lead?.industry || 'N/A'}</p>
                                </td>
                                <td className="px-8 py-5">
                                    <div className="flex items-center gap-3">
                                        <div className="p-1.5 rounded-lg bg-bg-elevated border border-border">
                                            <Icon icon="solar:calendar-mark-linear" width={14} className="text-brand" />
                                        </div>
                                        <div>
                                            <p className={`text-sm font-medium ${new Date(booking.scheduled_at) > new Date() ? 'text-ink' : 'text-ink-muted'}`}>
                                                {new Date(booking.scheduled_at).toLocaleDateString([], { month: 'short', day: 'numeric' })} at {new Date(booking.scheduled_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                                            </p>
                                            <p className="text-[11px] text-ink-faint mt-0.5">Confirmed</p>
                                        </div>
                                    </div>
                                </td>
                                <td className="px-8 py-5 text-right">
                                    <code className="text-[11px] font-mono bg-bg-elevated px-2 py-1 rounded-md text-ink-muted border border-border">
                                        {booking.calendly_event_id.slice(0, 8)}
                                    </code>
                                </td>
                                <td className="px-8 py-5 text-right">
                                    <Badge variant="state" value={booking.status.toUpperCase()} label="Status" />
                                </td>
                                <td className="px-8 py-5 text-right">
                                    <button
                                        onClick={() => booking.lead && onViewLead(booking.lead)}
                                        className="btn-secondary !py-2 !px-4"
                                    >
                                        View Lead
                                    </button>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
                {bookings.length === 0 && (
                    <div className="py-32 text-center space-y-6">
                        <div className="w-20 h-20 bg-bg-elevated border border-border rounded-full flex items-center justify-center mx-auto">
                            <Icon icon="solar:calendar-mark-linear" width={32} className="text-ink-faint" />
                        </div>
                        <p className="text-ink-muted text-sm">No bookings found</p>
                    </div>
                )}
            </div>
        </div>
    )
}
