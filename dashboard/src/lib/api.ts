// Read-only client for the reddit-outreach backend JSON API (/api/*).
// Phase 1 is read-only: this module never writes. Config (API base + client
// token + campaign) is read from Vite env first, then localStorage, so it works
// both on Vercel (env) and via the in-app connection screen (localStorage).

const LS_BASE = 'markeye_api_base'
const LS_TOKEN = 'markeye_client_token'
const LS_CAMPAIGN = 'markeye_campaign'
const LS_DEMO = 'markeye_demo_mode'

function ls(key: string): string {
    try {
        return localStorage.getItem(key) || ''
    } catch {
        return ''
    }
}

// Default backend for local dev so `npm run dev` / the Docker demo work with
// zero config. Production sets VITE_API_BASE explicitly at build time.
const DEFAULT_LOCAL_BASE = 'http://localhost:8010'

export function apiBase(): string {
    const env = (import.meta.env.VITE_API_BASE as string) || ''
    const base = env || ls(LS_BASE) || DEFAULT_LOCAL_BASE
    return base.replace(/\/$/, '')
}

export function clientToken(): string {
    return (import.meta.env.VITE_CLIENT_TOKEN as string) || ls(LS_TOKEN)
}

export function campaign(): string {
    return (import.meta.env.VITE_CAMPAIGN as string) || ls(LS_CAMPAIGN)
}

// Demo mode: render the UI against local mock data, no backend needed.
// A configured backend (env or saved) always wins over a stale demo flag.
export const isDemoMode = !apiBase() && ls(LS_DEMO) === 'true'

export function hasValidConfig(): boolean {
    if (isDemoMode) return true
    return !!apiBase()
}

// Kept the name `updateSupabaseConfig` so App.tsx/ConnectionScreen don't need to
// change their imports. Here `url` = backend API base, `key` = client token.
export function updateSupabaseConfig(url: string, key: string): void {
    try {
        localStorage.setItem(LS_BASE, url.replace(/\/$/, ''))
        localStorage.setItem(LS_TOKEN, key)
        localStorage.removeItem(LS_DEMO)
    } catch {
        /* ignore */
    }
    window.location.reload()
}

export function setCampaign(name: string): void {
    try {
        localStorage.setItem(LS_CAMPAIGN, name)
    } catch {
        /* ignore */
    }
}

export function enableDemoMode(): void {
    try {
        localStorage.setItem(LS_DEMO, 'true')
    } catch {
        /* ignore */
    }
    window.location.reload()
}

export function disconnect(): void {
    try {
        localStorage.removeItem(LS_BASE)
        localStorage.removeItem(LS_TOKEN)
        localStorage.removeItem(LS_CAMPAIGN)
        localStorage.removeItem(LS_DEMO)
    } catch {
        /* ignore */
    }
}

// Core fetch: GET `${base}/api${path}?campaign=...&token=...`.
export async function fetchJSON<T = unknown>(
    path: string,
    params: Record<string, string> = {}
): Promise<T> {
    const base = apiBase()
    if (!base) throw new Error('No API base configured')

    const qs = new URLSearchParams(params)
    const camp = campaign()
    if (camp && !qs.has('campaign')) qs.set('campaign', camp)
    const token = clientToken()
    if (token) qs.set('token', token)

    const res = await fetch(`${base}/api${path}?${qs.toString()}`, {
        cache: 'no-store',
        headers: token ? { 'X-Client-Token': token } : undefined,
    })
    if (!res.ok) throw new Error(`API ${res.status}`)
    return (await res.json()) as T
}
