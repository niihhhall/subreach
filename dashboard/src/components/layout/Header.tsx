import React, { useState, useEffect } from 'react'
import { Icon } from '@iconify/react'

interface HeaderProps {
    title: string
    isConnected: boolean
    lastUpdated: Date
    leadsCount: number
    onToggleMenu: () => void
}

export const Header: React.FC<HeaderProps> = ({
    title,
    isConnected,
    lastUpdated,
    leadsCount,
    onToggleMenu
}) => {
    const [seconds, setSeconds] = useState(0)

    useEffect(() => {
        const i = setInterval(() => {
            setSeconds(Math.floor((new Date().getTime() - lastUpdated.getTime()) / 1000))
        }, 1000)
        return () => clearInterval(i)
    }, [lastUpdated])

    return (
        <header className="h-[72px] border-b border-border flex items-center justify-between px-6 lg:px-8 bg-white/80 backdrop-blur-xl sticky top-0 z-30">
            <div className="flex items-center gap-4">
                <button
                    onClick={onToggleMenu}
                    className="lg:hidden w-10 h-10 rounded-xl bg-brand-muted flex items-center justify-center text-ink-soft hover:text-brand transition-all border border-border"
                >
                    <Icon icon="solar:hamburger-menu-linear" width="22" />
                </button>
                <div className="flex flex-col">
                    <h1 className="text-lg lg:text-xl font-bold tracking-tight text-ink leading-tight">{title}</h1>
                    <p className="text-[11px] text-ink-muted font-medium">Real-time overview of your lead pipeline</p>
                </div>
            </div>

            <div className="flex items-center gap-3">
                <div className="hidden md:flex items-center gap-2.5 bg-white border border-border px-4 py-2 rounded-xl shadow-card">
                    <span className={`w-2 h-2 rounded-full ${isConnected ? 'bg-emerald-500 animate-pulse-dot' : 'bg-amber-500 animate-pulse'}`}></span>
                    <span className={`text-xs font-semibold ${isConnected ? 'text-emerald-600' : 'text-amber-600'}`}>
                        {isConnected ? 'Live' : 'Reconnecting'}
                    </span>
                    <span className="text-ink-faint text-xs font-medium">·</span>
                    <span className="text-[11px] text-ink-muted font-medium">Synced {seconds}s ago</span>
                </div>

                <div className="hidden sm:flex items-center gap-2 bg-brand-muted border border-brand/15 px-4 py-2 rounded-xl">
                    <Icon icon="solar:users-group-two-rounded-bold" width="16" className="text-brand" />
                    <span className="text-xs font-semibold text-brand">{leadsCount} leads</span>
                </div>

                {!isConnected && (
                    <div className="md:hidden w-9 h-9 rounded-xl bg-amber-50 border border-amber-200 flex items-center justify-center text-amber-500">
                        <Icon icon="solar:danger-triangle-linear" width="18" className="animate-pulse" />
                    </div>
                )}

                <div className="hidden md:flex w-9 h-9 rounded-full bg-brand items-center justify-center text-white ring-2 ring-white shadow-card cursor-pointer hover:scale-105 transition-transform">
                    <Icon icon="solar:user-rounded-bold" width={18} />
                </div>
            </div>
        </header>
    )
}
