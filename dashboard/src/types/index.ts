// UI data models. These are shaped for the dashboard components. The backend
// (reddit-outreach FastAPI /api/*) is mapped onto these shapes in lib/adapters.ts,
// so a "Lead" here is a Reddit post/prospect, a "Message" is post-body + our draft,
// and "ConversationState" is synthesized from the lead's pipeline stage.

export interface Lead {
    id: string
    first_name: string
    last_name: string
    email: string
    phone: string
    company: string
    industry: string
    // Relaxed to string so a subreddit / source label maps cleanly.
    lead_source: string
    form_message: string
    temperature: 'Cold' | 'Warm' | 'Hot'
    outcome: 'In Progress' | 'Not Interested' | 'Disqualified' | 'Meeting Booked'
    signal_score: number
    created_at: string
    updated_at: string

    // ── reddit-outreach extras (optional; used by adapters + detail views) ──
    subreddit?: string
    title?: string
    url?: string
    pains?: string[]
    priority?: number
    tier?: string
    num_comments?: number
    saturation?: string
    sent?: boolean
    draft?: string
    angle?: string
    stage?: string
    verdict?: string
}

export interface Message {
    id: string
    lead_id: string
    direction: 'inbound' | 'outbound'
    content: string
    created_at: string
    leads?: Partial<Lead>
}

export interface ConversationState {
    id: string
    lead_id: string
    current_state: 'Opening' | 'Discovery' | 'Qualification' | 'Intent Building' | 'Booking Push' | 'Awaiting' | 'Confirmed' | 'Escalation'
    bant_budget: string | null
    bant_authority: string | null
    bant_need: string | null
    bant_timeline: string | null
    message_count: number
    is_typing?: boolean
    last_active_at: string
    updated_at: string
}

export interface Booking {
    id: string
    lead_id: string
    calendly_event_id: string
    scheduled_at: string
    status: string
    created_at: string
    leads?: Partial<Lead>
}

export interface LLMSession {
    id: string
    lead_id: string | null
    helicone_id: string
    model: string
    prompt_tokens: number
    completion_tokens: number
    total_tokens: number
    cost_usd: number
    latency_ms: number
    conversation_state: string
    created_at: string
}

export type ConversationStateName = ConversationState['current_state']

export interface Client {
    id: string
    business_name: string
    whatsapp_number: string
    api_key: string
    is_active: boolean
    sales_contact: string | null
    created_at: string
}

export interface BaileysSession {
    sessionId: string
    status: 'connected' | 'pairing' | 'offline' | 'connecting'
    qr?: string
    error?: string
}

// ── raw backend response shapes (reddit-outreach /api/*) ──
export interface ApiActivity {
    ts?: number
    action?: string
    channel?: string
    subreddit?: string
    author?: string
    account?: string
    status?: string
    post_id?: string
    detail?: string
}

export interface ApiLead {
    id: string
    tier: string
    score: number
    priority: number
    age_days: number | null
    num_comments: number
    saturation: string
    subreddit: string
    title: string
    url: string
    pains: string[]
    sent: boolean
}

export interface ApiOverview {
    campaign: string
    product: string
    funnel: Record<string, number>
    total: number
    engageable: number
    tiers: { hot: number; warm: number; cold: number }
    health: { status: string; score: number | null }
    breaker_open: boolean
    karma: number | null
    subreddits: { subreddit: string; leads: number; sent: number; avg_priority: number | null }[]
    recent: ApiActivity[]
}

export interface ApiQueueItem {
    id: string
    stage: string
    priority: number
    verdict: string
    subreddit: string
    title: string
    url: string
    draft: string
}

export interface ApiEngagementItem {
    id: string
    score: number
    value_add: number
    sub_fit: number
    age_days: number | null
    num_comments: number
    subreddit: string
    title: string
    url: string
    angle: string
    draft: string
    quality: { verdict: string; helpful: number; human: number } | null
}

export interface ApiSwarmAccount {
    label: string
    subreddits: string[]
    persona: string
    today: number
    cap: number
    karma: number | null
    status: string
    breaker_open: boolean
    awake: boolean
    active_hours: string
    tz_offset: number
    has_key: boolean
}

export interface ApiHealth {
    account: string
    status: string
    score: number | null
    signals: Record<string, unknown>
    breaker_open: boolean
    breaker_reason: string
    karma_trend: { ts: number; total_karma: number }[]
    history: { ts: number; status: string; score: number | null; detail: string }[]
    verifications: ApiActivity[]
}

export interface ApiScoutSub {
    subreddit: string
    relevance: number
    active: boolean
    sample_count: number
    last_seen: number | null
}

export interface ApiScout {
    verticals: Record<string, ApiScoutSub[]>
    total: number
    active: number
}

export interface ApiOutreach {
    dm_enabled: boolean
    counts: { dm_drafts: number; dm_sent: number; handed_off: number; pending: number }
    dm_drafts: unknown[]
    handoffs: ApiActivity[]
    pending: { id: string; author: string; stage: string; priority: number; title: string; url: string }[]
}

export interface ApiTimeseries {
    series: { date: string; leads: number; comments: number }[]
}
