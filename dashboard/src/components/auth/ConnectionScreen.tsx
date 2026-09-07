import React, { useState } from 'react'
import { Icon } from '@iconify/react'
import { enableDemoMode } from '../../lib/api'

interface ConnectionScreenProps {
    onConnect: (url: string, key: string) => void
}

export const ConnectionScreen: React.FC<ConnectionScreenProps> = ({ onConnect }) => {
    const [url, setUrl] = useState(localStorage.getItem('markeye_api_base') || '')
    const [key, setKey] = useState(localStorage.getItem('markeye_client_token') || '')

    const handleSubmit = (e: React.FormEvent) => {
        e.preventDefault()
        // API base is required; the client token is required only if the backend
        // has CLIENT_TOKEN configured (it usually does), but we let the user try.
        if (url) {
            onConnect(url, key)
        }
    }

    return (
        <div className="min-h-screen bg-bg-base flex items-center justify-center p-6">
            <div className="w-full max-w-md space-y-8 animate-in fade-in zoom-in duration-700">
                <div className="text-center space-y-5">
                    <div className="mx-auto w-14 h-14 rounded-2xl overflow-hidden shadow-lift">
                        <img src="/markeye-logo.png" alt="MarkEye logo" className="w-full h-full object-cover" />
                    </div>
                    <h1 className="text-3xl font-bold text-ink tracking-tight">
                        Mark<span className="text-brand">Eye</span>
                    </h1>
                    <p className="text-sm text-ink-muted">Connect your workspace to get started</p>
                </div>

                <div className="card p-8 relative overflow-hidden">
                    <form onSubmit={handleSubmit} className="space-y-6 relative z-10">
                        <div className="space-y-6">
                            <div className="space-y-2">
                                <label className="block text-xs font-semibold text-ink-soft pl-1">Backend API URL</label>
                                <input
                                    type="text"
                                    value={url}
                                    onChange={(e) => setUrl(e.target.value)}
                                    placeholder="https://your-outreach-app.herokuapp.com"
                                    className="input-modern w-full"
                                    required
                                />
                            </div>
                            <div className="space-y-2">
                                <label className="block text-xs font-semibold text-ink-soft pl-1">Client Token</label>
                                <input
                                    type="password"
                                    value={key}
                                    onChange={(e) => setKey(e.target.value)}
                                    placeholder="CLIENT_TOKEN from the backend"
                                    className="input-modern w-full"
                                />
                            </div>
                        </div>

                        <div className="space-y-3 pt-2">
                            <button
                                type="submit"
                                className="btn-premium w-full flex items-center justify-center gap-2 group/btn"
                            >
                                Connect <Icon icon="solar:arrow-right-linear" width={18} className="group-hover/btn:translate-x-1 transition-transform" />
                            </button>

                            <button
                                type="button"
                                onClick={enableDemoMode}
                                className="btn-secondary w-full flex items-center justify-center gap-2 group/demo"
                            >
                                <Icon icon="solar:play-circle-linear" width={18} className="text-brand group-hover/demo:scale-110 transition-transform" />
                                Start Demo Mode
                            </button>
                        </div>
                    </form>
                </div>

                <div className="flex items-center justify-center gap-6 text-[11px] text-ink-faint pt-4 font-medium">
                    <div className="flex items-center gap-2">
                        <Icon icon="solar:shield-check-linear" width={16} /> Encrypted Connection
                    </div>
                    <div className="w-1 h-1 rounded-full bg-gray-300"></div>
                    <div>v4.1.0</div>
                </div>
            </div>
        </div>
    )
}
