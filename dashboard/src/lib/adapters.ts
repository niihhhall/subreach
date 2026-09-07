// Maps reddit-outreach backend responses onto the dashboard's UI types.
// A Reddit "prospect" becomes a Lead; the post + our drafted reply become a
// Message thread; the pipeline stage/tier becomes a ConversationState.

import type {
    ApiActivity,
    ApiLead,
    ApiScoutSub,
    ApiSwarmAccount,
    Booking,
    Client,
    BaileysSession,
    ConversationState,
    Lead,
    Message,
} from '../types'

const DAY_MS = 86_400_000

// Capitalize only the first character (preserves "DM", hyphens like "after-hours").
export function capitalizeFirst(s: string): string {
    if (!s) return s
    return s.charAt(0).toUpperCase() + s.slice(1)
}

export function tierToTemperature(tier?: string): Lead['temperature'] {
    switch ((tier || '').toLowerCase()) {
        case 'hot':
            return 'Hot'
        case 'warm':
            return 'Warm'
        default:
            return 'Cold'
    }
}

// Backend triage/priority is 0–100; the UI SignalScore/bars expect 0–10.
export function to10(score?: number | null): number {
    const n = Math.round((score || 0) / 10)
    return Math.max(0, Math.min(10, n))
}

function agoIso(ageDays?: number | null): string {
    const days = ageDays && ageDays > 0 ? ageDays : 0
    return new Date(Date.now() - days * DAY_MS).toISOString()
}

// Map a pipeline stage / tier / sent-flag to the UI's disposition + state.
export function stageToOutcome(lead: ApiLead): Lead['outcome'] {
    if (lead.sent) return 'Meeting Booked'
    if ((lead.tier || '').toLowerCase() === 'cold') return 'In Progress'
    return 'In Progress'
}

export function leadToStateName(lead: Lead): ConversationState['current_state'] {
    if (lead.sent) return 'Awaiting'
    switch ((lead.tier || '').toLowerCase()) {
        case 'hot':
            return 'Booking Push'
        case 'warm':
            return 'Qualification'
        default:
            return 'Discovery'
    }
}

export function adaptLead(a: ApiLead): Lead {
    const created = agoIso(a.age_days)
    const subLabel = a.subreddit ? `r/${a.subreddit}` : ''
    return {
        id: a.id,
        // The post title is the human-readable identity in cards/detail.
        first_name: a.title || subLabel || 'Reddit lead',
        last_name: '',
        email: '',
        phone: subLabel, // shown with an icon in cards; the subreddit is the "handle"
        company: subLabel,
        industry: a.saturation || '',
        lead_source: a.subreddit || 'Other',
        form_message: (a.pains && a.pains.length ? a.pains.join(' · ') : a.title) || '',
        temperature: tierToTemperature(a.tier),
        outcome: stageToOutcome(a),
        signal_score: to10(a.score ?? a.priority),
        created_at: created,
        updated_at: created,
        subreddit: a.subreddit,
        title: a.title,
        url: a.url,
        pains: a.pains || [],
        priority: a.priority,
        tier: a.tier,
        num_comments: a.num_comments,
        saturation: a.saturation,
        sent: a.sent,
    }
}

// Synthesize a lightweight conversation-state from a lead (no BANT backend).
export function adaptState(lead: Lead): ConversationState {
    const pains = lead.pains || []
    return {
        id: `state-${lead.id}`,
        lead_id: lead.id,
        current_state: leadToStateName(lead),
        bant_need: pains[0] || null,
        bant_budget: null,
        bant_authority: null,
        bant_timeline: null,
        message_count: lead.draft ? 2 : 1,
        is_typing: false,
        last_active_at: lead.updated_at,
        updated_at: lead.updated_at,
    }
}

// Build a "conversation" from the Reddit post (inbound) + our draft (outbound).
export function buildMessages(
    lead: Lead,
    opts: { draft?: string; angle?: string } = {}
): Message[] {
    const out: Message[] = []
    const postBody =
        (lead.title ? lead.title : '') +
        (lead.pains && lead.pains.length ? `\n\nSignals: ${lead.pains.join(', ')}` : '')
    out.push({
        id: `${lead.id}-post`,
        lead_id: lead.id,
        direction: 'inbound',
        content: postBody || '(original Reddit post)',
        created_at: lead.created_at,
    })
    const draft = opts.draft || lead.draft
    if (draft) {
        out.push({
            id: `${lead.id}-draft`,
            lead_id: lead.id,
            direction: 'outbound',
            content: draft,
            created_at: lead.updated_at,
        })
    }
    return out
}

// ── swarm accounts -> Instances page (Client + session status) ──
export function adaptSwarmClient(a: ApiSwarmAccount): Client {
    return {
        id: a.label,
        business_name: a.label,
        whatsapp_number:
            (a.subreddits && a.subreddits.length ? a.subreddits.map((s) => `r/${s}`).join(', ') : a.persona) ||
            'no subreddits',
        api_key: a.has_key ? 'configured' : '',
        is_active: a.has_key,
        sales_contact: a.persona || null,
        created_at: new Date().toISOString(),
    }
}

export function adaptSwarmSession(a: ApiSwarmAccount): BaileysSession {
    let status: BaileysSession['status'] = 'offline'
    if (a.breaker_open) status = 'offline'
    else if (!a.has_key) status = 'offline'
    else if ((a.status || '').toLowerCase() === 'ok' || a.awake) status = 'connected'
    else status = 'connecting'
    return { sessionId: a.label, status }
}

// ── handoffs -> Bookings page rows ──
export function activityToBooking(a: ApiActivity): Booking & { lead?: Lead } {
    const sub = a.subreddit ? `r/${a.subreddit}` : ''
    const lead: Partial<Lead> = {
        first_name: a.author ? `u/${a.author}` : sub || 'lead',
        last_name: '',
        company: sub,
        lead_source: a.subreddit || 'Other',
        industry: '',
    }
    return {
        id: a.post_id || `${a.ts}`,
        lead_id: a.post_id || '',
        calendly_event_id: a.post_id || (a.detail || '').slice(0, 12) || 'handoff',
        scheduled_at: new Date((a.ts || 0) * 1000).toISOString(),
        status: a.status === 'sent' ? 'confirmed' : a.status || 'pending',
        created_at: new Date((a.ts || 0) * 1000).toISOString(),
        lead: lead as Lead,
    }
}

// ── queue items (/api/queue) -> Lead (for the Review page) ──
export function priorityToTier(priority: number): string {
    if (priority >= 70) return 'hot'
    if (priority >= 50) return 'warm'
    return 'cold'
}

export function queueItemToLead(q: {
    id: string; stage: string; priority: number; verdict: string
    subreddit: string; title: string; url: string; draft: string
}): Lead {
    const tier = priorityToTier(q.priority)
    const sub = q.subreddit ? `r/${q.subreddit}` : ''
    return {
        id: q.id,
        first_name: q.title || sub || 'Draft',
        last_name: '',
        email: '',
        phone: sub,
        company: sub,
        industry: '',
        lead_source: q.subreddit || 'Other',
        form_message: q.title || '',
        temperature: tierToTemperature(tier),
        outcome: 'In Progress',
        signal_score: to10(q.priority),
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        subreddit: q.subreddit,
        title: q.title,
        url: q.url,
        pains: [],
        priority: q.priority,
        tier,
        draft: q.draft,
        stage: q.stage,
        verdict: q.verdict,
    }
}

export type ScoutRow = ApiScoutSub & { vertical: string }

export function flattenScout(verticals: Record<string, ApiScoutSub[]>): ScoutRow[] {
    const rows: ScoutRow[] = []
    for (const [vertical, subs] of Object.entries(verticals || {})) {
        for (const s of subs) rows.push({ ...s, vertical })
    }
    return rows.sort((a, b) => (b.relevance || 0) - (a.relevance || 0))
}
